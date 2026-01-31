"""
Research execution routes.

Start, pause, resume, and manage research graph execution.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from backend.api.dependencies import get_current_user
from backend.api.websocket import WSEventType, create_ws_event, get_connection_manager
from backend.persistence.database import DatabaseService, get_db_service
from backend.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


class StartResearchRequest(BaseModel):
    """Request to start or resume research."""

    run_id: str
    message: Optional[str] = None  # Initial query or follow-up message


class StartResearchResponse(BaseModel):
    """Response for start research request."""

    status: str
    run_id: str
    message: str


class PauseRequest(BaseModel):
    """Request to pause research."""

    run_id: str


class ResearchStateResponse(BaseModel):
    """Response with current research state."""

    run_id: str
    phase: str
    plan: List[Dict[str, Any]]
    current_step_index: int
    messages: List[Dict[str, Any]]
    is_running: bool


@router.post("/start", response_model=StartResearchResponse)
async def start_research(
    request: StartResearchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Start or resume research execution.

    Runs the research graph in a background task.
    Connect via WebSocket to receive real-time updates.
    """
    # Verify run ownership
    run = await db.get_run(request.run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this run",
        )

    logger.info(f"Starting research for run {request.run_id}")

    # Import service here to avoid circular imports
    from backend.services.research_service import get_research_service

    service = await get_research_service()

    # Add execution to background tasks
    background_tasks.add_task(
        service.execute_research,
        run_id=request.run_id,
        user_id=current_user.id,
        initial_query=request.message or run.title,
    )

    # Broadcast start event
    manager = get_connection_manager()
    await manager.broadcast(
        request.run_id,
        create_ws_event(WSEventType.RUN_START, run_id=request.run_id),
    )

    return StartResearchResponse(
        status="started",
        run_id=request.run_id,
        message="Research execution started. Connect via WebSocket for updates.",
    )


@router.post("/pause")
async def pause_research(
    request: PauseRequest,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Pause research execution at next checkpoint.
    """
    run = await db.get_run(request.run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    from backend.services.research_service import get_research_service

    service = await get_research_service()
    await service.pause_research(request.run_id)

    # Update run status
    await db.update_run(request.run_id, status="paused")

    logger.info(f"Pause requested for run {request.run_id}")

    return {"status": "pausing", "run_id": request.run_id}


class ResumeRequest(BaseModel):
    """Request to resume an interrupted run."""

    run_id: str


@router.post("/resume")
async def resume_interrupted(
    request: ResumeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Resume an interrupted research run.

    Used when a run was interrupted by server crash/restart.
    Continues execution from the last checkpoint.
    """
    run = await db.get_run(request.run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    if run.status not in ("interrupted", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run cannot be resumed (status: {run.status})",
        )

    from backend.services.research_service import get_research_service

    service = await get_research_service()

    # Check if already running (use DB status as source of truth)
    if run.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is already executing",
        )

    logger.info(f"Resuming interrupted run {request.run_id}")

    background_tasks.add_task(
        service.resume_interrupted,
        run_id=request.run_id,
    )

    # Broadcast start event
    manager = get_connection_manager()
    await manager.broadcast(
        request.run_id,
        create_ws_event(WSEventType.RUN_START, run_id=request.run_id),
    )

    return {
        "status": "resuming",
        "run_id": request.run_id,
        "message": "Resuming interrupted research from last checkpoint",
    }


@router.post("/message")
async def send_message(
    request: StartResearchRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Send a message to a research run.

    If research hasn't started yet, this starts it with the message as the query.
    If research is paused/waiting, this resumes it with the message as user input.
    """
    if not request.message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message is required",
        )

    run = await db.get_run(request.run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    from backend.services.research_service import get_research_service

    service = await get_research_service()

    # Check if state exists (research has been started before)
    existing_state = await service.get_state(request.run_id)

    if existing_state is None:
        # No state exists - this is the first message, start research
        logger.info(f"No existing state for run {request.run_id}, starting research")
        background_tasks.add_task(
            service.execute_research,
            run_id=request.run_id,
            user_id=current_user.id,
            initial_query=request.message,
        )

        # Broadcast start event
        manager = get_connection_manager()
        await manager.broadcast(
            request.run_id,
            create_ws_event(WSEventType.RUN_START, run_id=request.run_id),
        )

        return {
            "status": "started",
            "run_id": request.run_id,
            "message": "Research started with your query",
        }
    else:
        # State exists - resume with user input
        logger.info(f"Resuming run {request.run_id} with user input")
        background_tasks.add_task(
            service.resume_with_input,
            run_id=request.run_id,
            user_input=request.message,
        )

        return {
            "status": "resuming",
            "run_id": request.run_id,
            "message": "Resuming with user input",
        }


@router.get("/state/{run_id}", response_model=ResearchStateResponse)
async def get_research_state(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Get current research state from the graph checkpoint.
    """
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    from backend.services.research_service import get_research_service

    service = await get_research_service()
    state = await service.get_state(run_id)

    if not state:
        return ResearchStateResponse(
            run_id=run_id,
            phase="not_started",
            plan=[],
            current_step_index=0,
            messages=[],
            is_running=False,
        )

    # Convert messages to dicts
    messages = []
    for msg in state.get("messages", []):
        if hasattr(msg, "content"):
            messages.append({
                "role": getattr(msg, "type", "unknown"),
                "content": msg.content,
                "name": getattr(msg, "name", None),
            })

    return ResearchStateResponse(
        run_id=run_id,
        phase=state.get("phase", "unknown"),
        plan=state.get("plan", []),
        current_step_index=state.get("current_step_index", 0),
        messages=messages,
        is_running=run.status == "active",  # Use DB status as source of truth
    )
