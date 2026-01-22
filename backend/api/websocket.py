"""
WebSocket connection manager for real-time updates.

Manages WebSocket connections per run_id and broadcasts events.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Connections are organized by run_id for targeted broadcasting.
    """

    def __init__(self):
        # run_id -> set of connected websockets
        self.connections: Dict[str, Set[WebSocket]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        """
        Accept and register a WebSocket connection.

        Args:
            run_id: Run ID to associate with this connection
            websocket: WebSocket connection
        """
        await websocket.accept()

        async with self._lock:
            if run_id not in self.connections:
                self.connections[run_id] = set()
            self.connections[run_id].add(websocket)

        logger.info(f"WebSocket connected for run {run_id}")

    async def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            run_id: Run ID associated with connection
            websocket: WebSocket to remove
        """
        async with self._lock:
            if run_id in self.connections:
                self.connections[run_id].discard(websocket)
                if not self.connections[run_id]:
                    del self.connections[run_id]

        logger.info(f"WebSocket disconnected for run {run_id}")

    async def broadcast(self, run_id: str, message: dict) -> None:
        """
        Broadcast a message to all connections for a run.

        Args:
            run_id: Run ID to broadcast to
            message: Message dict to send as JSON
        """
        async with self._lock:
            connections = self.connections.get(run_id, set()).copy()

        if not connections:
            return

        # Send to all connections, removing dead ones
        dead_connections = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to WebSocket: {e}")
                dead_connections.append(ws)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    if run_id in self.connections:
                        self.connections[run_id].discard(ws)

    async def send_personal(
        self, run_id: str, websocket: WebSocket, message: dict
    ) -> bool:
        """
        Send a message to a specific WebSocket.

        Args:
            run_id: Run ID (for logging)
            websocket: Target WebSocket
            message: Message to send

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.debug(f"Failed to send personal message: {e}")
            return False

    def get_connection_count(self, run_id: Optional[str] = None) -> int:
        """
        Get number of active connections.

        Args:
            run_id: If provided, count for specific run. Otherwise, total.

        Returns:
            Number of active connections
        """
        if run_id:
            return len(self.connections.get(run_id, set()))
        return sum(len(conns) for conns in self.connections.values())


# Global connection manager instance
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the global ConnectionManager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


# Event types for WebSocket messages
class WSEventType:
    """WebSocket event type constants."""

    # Phase changes
    PHASE_CHANGE = "phase_change"

    # Messages
    MESSAGE = "message"
    TOOL_CALL = "tool_call"

    # Research progress
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    SEARCH_START = "search_start"
    SEARCH_COMPLETE = "search_complete"
    SEARCH_PARALLEL = "search_parallel"

    # Human-in-the-loop
    APPROVAL_NEEDED = "approval_needed"
    APPROVAL_RESPONSE = "approval_response"
    QUESTION = "question"

    # Status
    RUN_START = "run_start"
    RUN_COMPLETE = "run_complete"
    RUN_ERROR = "run_error"
    RUN_PAUSED = "run_paused"


def create_ws_event(event_type: str, **data) -> dict:
    """
    Create a WebSocket event message.

    Args:
        event_type: Event type from WSEventType
        **data: Additional event data

    Returns:
        Event dict ready for JSON serialization
    """
    return {"type": event_type, **data}
