"""
Terminal prepare node - prepares terminal command for approval.

Sets pending_terminal and phase for interrupt handling.
"""

import logging

from backend.agents.state import ResearchState
from backend.agents.tools.filesystem import get_command_hash

logger = logging.getLogger(__name__)


async def terminal_prepare_node(state: ResearchState) -> dict:
    """
    Prepare terminal command execution.

    Sets pending_terminal with command details and changes phase
    to awaiting_terminal for human-in-the-loop approval.
    """
    run_id = state.get("run_id", "")
    decision = state.get("executor_decision", {})
    params = decision.get("params", {})

    command = params.get("command", "")
    timeout = params.get("timeout", 60)

    if not command:
        logger.warning(f"Terminal prepare called without command for run {run_id}")
        return {
            "pending_terminal": None,
            "last_error": "Terminal command was empty",
        }

    # Generate hash for approval tracking
    command_hash = get_command_hash(command)

    logger.info(f"Terminal prepare: {command[:50]}...")

    return {
        "pending_terminal": {
            "command": command,
            "hash": command_hash,
            "timeout": timeout,
        },
        "phase": "awaiting_terminal",
    }
