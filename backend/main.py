"""
FastAPI application entry point.

Main application with lifespan management for startup/shutdown.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import api_router
from backend.api.websocket import get_connection_manager
from backend.core.config import config
from backend.core.checkpointer import get_checkpointer, close_checkpointer
from backend.persistence.database import get_db_service

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup initialization and shutdown cleanup.
    """
    logger.info("Starting application...")

    # Ensure db directory exists
    db_dir = Path(config.database.base_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database
    db = await get_db_service()
    logger.info("Database initialized")

    # Initialize checkpointer
    checkpointer = await get_checkpointer()
    app.state.checkpointer = checkpointer
    logger.info("Checkpointer initialized")

    # Store services in app state for access in routes
    app.state.db = db

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    await close_checkpointer()
    logger.info("Application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=config.app_name,
    description="A LangGraph-based multi-agent research system",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router)


# WebSocket endpoint
@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    """
    WebSocket endpoint for real-time research updates.

    Connect to receive:
    - Phase changes
    - Messages and tool calls
    - Step progress
    - Approval requests
    - Errors
    """
    manager = get_connection_manager()
    await manager.connect(run_id, websocket)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "run_id": run_id,
            "message": "WebSocket connected successfully",
        })

        # Send current state sync
        from backend.services.research_service import get_research_service
        try:
            service = await get_research_service()
            state = await service.get_state(run_id)
            is_running = service.is_running(run_id)

            # Convert messages to dicts
            messages = []
            if state:
                for msg in state.get("messages", []):
                    if hasattr(msg, "content"):
                        messages.append({
                            "role": getattr(msg, "type", "unknown"),
                            "content": msg.content,
                            "name": getattr(msg, "name", None),
                        })

            phase = state.get("phase", "idle") if state else "idle"
            pending_terminal = state.get("pending_terminal") if state else None

            await websocket.send_json({
                "type": "state_sync",
                "run_id": run_id,
                "is_running": is_running,
                "phase": phase,
                "plan": state.get("plan", []) if state else [],
                "current_step_index": state.get("current_step_index", 0) if state else 0,
                "search_themes": state.get("search_themes", []) if state else [],
                "messages": messages,
                "pending_terminal": pending_terminal,
            })
        except Exception as e:
            logger.warning(f"Failed to send state sync for run {run_id}: {e}")

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages (client can send commands)
                data = await websocket.receive_json()

                # Handle client commands if needed
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data.get("type") == "request_state":
                    # Client requests state refresh
                    from backend.services.research_service import get_research_service
                    try:
                        service = await get_research_service()
                        state = await service.get_state(run_id)
                        is_running = service.is_running(run_id)

                        # Convert messages to dicts
                        messages = []
                        if state:
                            for msg in state.get("messages", []):
                                if hasattr(msg, "content"):
                                    messages.append({
                                        "role": getattr(msg, "type", "unknown"),
                                        "content": msg.content,
                                        "name": getattr(msg, "name", None),
                                    })

                        phase = state.get("phase", "idle") if state else "idle"
                        pending_terminal = state.get("pending_terminal") if state else None

                        await websocket.send_json({
                            "type": "state_sync",
                            "run_id": run_id,
                            "is_running": is_running,
                            "phase": phase,
                            "plan": state.get("plan", []) if state else [],
                            "current_step_index": state.get("current_step_index", 0) if state else 0,
                            "search_themes": state.get("search_themes", []) if state else [],
                            "messages": messages,
                            "pending_terminal": pending_terminal,
                        })
                    except Exception as e:
                        logger.warning(f"Failed to send state for run {run_id}: {e}")

            except WebSocketDisconnect:
                break

    finally:
        await manager.disconnect(run_id, websocket)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": config.app_name,
        "version": "2.0.0",
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": config.app_name,
        "version": "2.0.0",
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
