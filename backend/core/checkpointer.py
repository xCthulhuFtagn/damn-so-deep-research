"""
LangGraph checkpointer factory.

Provides AsyncSqliteSaver for state persistence.
"""

import logging
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.core.config import config

logger = logging.getLogger(__name__)

# Global checkpointer instance
_checkpointer: Optional[AsyncSqliteSaver] = None
_checkpointer_context = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    Get or create the AsyncSqliteSaver checkpointer.

    The checkpointer provides:
    - State persistence across restarts
    - Pause/resume capability
    - Time-travel debugging
    - Thread-based checkpoint organization

    Returns:
        AsyncSqliteSaver instance
    """
    global _checkpointer, _checkpointer_context

    if _checkpointer is None:
        # Ensure db directory exists
        db_dir = Path(config.database.base_dir)
        db_dir.mkdir(parents=True, exist_ok=True)

        db_path = config.database.langgraph_db_path
        logger.info(f"Initializing LangGraph checkpointer at: {db_path}")

        # from_conn_string returns an async context manager, we need to enter it
        _checkpointer_context = AsyncSqliteSaver.from_conn_string(db_path)
        _checkpointer = await _checkpointer_context.__aenter__()
        logger.info("Checkpointer initialized successfully")

    return _checkpointer


async def close_checkpointer() -> None:
    """Close the checkpointer connection."""
    global _checkpointer, _checkpointer_context

    if _checkpointer is not None and _checkpointer_context is not None:
        logger.info("Closing checkpointer connection")
        await _checkpointer_context.__aexit__(None, None, None)
        _checkpointer = None
        _checkpointer_context = None


def get_thread_config(run_id: str, user_id: str) -> dict:
    """
    Generate a config dict for graph invocation.

    Uses run_id as thread_id for checkpoint organization.

    Args:
        run_id: Unique run identifier
        user_id: User identifier

    Returns:
        Config dict with configurable thread_id
    """
    return {
        "configurable": {
            "thread_id": run_id,
            "user_id": user_id,
        }
    }
