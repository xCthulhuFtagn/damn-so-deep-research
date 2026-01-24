"""
Notification service for WebSocket event broadcasting.

Handles sending real-time updates to connected clients.
"""

import logging
from typing import Any, Dict, Optional

from backend.api.websocket import (
    ConnectionManager,
    WSEventType,
    create_ws_event,
    get_connection_manager,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for broadcasting notifications to WebSocket clients.

    Provides high-level methods for common notification types.
    """

    def __init__(self, connection_manager: ConnectionManager):
        self.manager = connection_manager

    async def notify_phase_change(
        self,
        run_id: str,
        phase: str,
        step: Optional[int] = None,
    ) -> None:
        """Notify clients of a phase change."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.PHASE_CHANGE,
                phase=phase,
                step=step,
            ),
        )

    async def notify_message(
        self,
        run_id: str,
        role: str,
        content: str,
        name: Optional[str] = None,
    ) -> None:
        """Notify clients of a new message."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.MESSAGE,
                role=role,
                content=content,
                name=name,
            ),
        )

    async def notify_tool_call(
        self,
        run_id: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[str] = None,
    ) -> None:
        """Notify clients of a tool call."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.TOOL_CALL,
                tool_name=tool_name,
                args=args,
                result=result,
            ),
        )

    async def notify_step_start(
        self,
        run_id: str,
        step_index: int,
        description: str,
    ) -> None:
        """Notify clients that a step is starting."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.STEP_START,
                step_index=step_index,
                description=description,
            ),
        )

    async def notify_step_complete(
        self,
        run_id: str,
        step_index: int,
        status: str,
        result: Optional[str] = None,
    ) -> None:
        """Notify clients that a step is complete."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.STEP_COMPLETE,
                step_index=step_index,
                status=status,
                result=result,
            ),
        )

    async def notify_plan_update(
        self,
        run_id: str,
        plan: list,
    ) -> None:
        """Notify clients of a full plan update."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.PLAN_UPDATE,
                plan=plan,
            ),
        )

    async def notify_search_parallel(
        self,
        run_id: str,
        themes: list[str],
    ) -> None:
        """Notify clients of parallel search themes."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.SEARCH_PARALLEL,
                themes=themes,
                count=len(themes),
            ),
        )

    async def notify_approval_needed(
        self,
        run_id: str,
        command: str,
        command_hash: str,
    ) -> None:
        """Notify clients that approval is needed."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.APPROVAL_NEEDED,
                command=command,
                command_hash=command_hash,
            ),
        )

    async def notify_plan_confirmation_needed(
        self,
        run_id: str,
        plan: list,
    ) -> None:
        """Notify clients that plan confirmation is needed."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.PLAN_CONFIRMATION_NEEDED,
                plan=plan,
            ),
        )

    async def notify_run_complete(
        self,
        run_id: str,
        report: Optional[str] = None,
    ) -> None:
        """Notify clients that the run is complete."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.RUN_COMPLETE,
                report=report,
            ),
        )

    async def notify_run_error(
        self,
        run_id: str,
        error: str,
    ) -> None:
        """Notify clients of an error."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.RUN_ERROR,
                error=error,
            ),
        )

    async def notify_run_paused(
        self,
        run_id: str,
        reason: Optional[str] = None,
    ) -> None:
        """Notify clients that the run is paused."""
        await self.manager.broadcast(
            run_id,
            create_ws_event(
                WSEventType.RUN_PAUSED,
                reason=reason,
            ),
        )


# Global instance
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global NotificationService instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(get_connection_manager())
    return _notification_service
