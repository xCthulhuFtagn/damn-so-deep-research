"""
Approval routes for command execution.

Handles human-in-the-loop approval for terminal commands.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.api.dependencies import get_current_user
from backend.api.websocket import WSEventType, create_ws_event, get_connection_manager
from backend.persistence.database import DatabaseService, get_db_service
from backend.persistence.models import Approval, ApprovalResponse, User

logger = logging.getLogger(__name__)

router = APIRouter()


class ApprovalItem(BaseModel):
    """Response model for an approval item."""

    command_hash: str
    run_id: str
    command_text: str
    approved: int  # 0 = pending, 1 = approved, -1 = denied


class PendingApprovalsResponse(BaseModel):
    """Response model for pending approvals."""

    approvals: List[ApprovalItem]
    count: int


@router.get("/{run_id}", response_model=PendingApprovalsResponse)
async def get_pending_approvals(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Get all pending approvals for a run.
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

    approvals = await db.get_pending_approvals(run_id)

    return PendingApprovalsResponse(
        approvals=[
            ApprovalItem(
                command_hash=a.command_hash,
                run_id=a.run_id,
                command_text=a.command_text,
                approved=a.approved,
            )
            for a in approvals
        ],
        count=len(approvals),
    )


@router.post("/{run_id}/{command_hash}")
async def respond_to_approval(
    run_id: str,
    command_hash: str,
    response: ApprovalResponse,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Respond to an approval request (approve or deny).
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

    # Check if approval exists
    approval = await db.get_approval(run_id, command_hash)
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found",
        )

    # Update approval status
    updated = await db.respond_to_approval(run_id, command_hash, response.approved)

    logger.info(
        f"Approval response for {command_hash}: {'approved' if response.approved else 'denied'}"
    )

    # Broadcast approval response
    manager = get_connection_manager()
    await manager.broadcast(
        run_id,
        create_ws_event(
            WSEventType.APPROVAL_RESPONSE,
            command_hash=command_hash,
            approved=response.approved,
        ),
    )

    # If approved, the research service will pick up the response
    # via polling or we can notify it directly
    from backend.services.research_service import get_research_service

    service = await get_research_service()
    await service.handle_approval_response(run_id, command_hash, response.approved)

    return {
        "status": "success",
        "approved": response.approved,
        "command_hash": command_hash,
    }
