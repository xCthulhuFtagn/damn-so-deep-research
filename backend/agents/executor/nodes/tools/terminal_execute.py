"""
Terminal execute node - executes approved terminal commands.

Called after human approval grants permission.
"""

import logging

from backend.agents.state import ExecutorToolCall, ResearchState
from backend.core.config import config
from backend.agents.tools.filesystem import execute_command

logger = logging.getLogger(__name__)


async def terminal_execute_node(state: ResearchState) -> dict:
    """
    Execute the approved terminal command.

    Assumes approval has been granted via the interrupt mechanism.
    Records result in executor_tool_history.
    """
    run_id = state.get("run_id", "")
    pending = state.get("pending_terminal", {})
    tool_history = state.get("executor_tool_history", [])
    call_count = state.get("executor_call_count", 0)

    command = pending.get("command", "")
    timeout = pending.get("timeout", 60)

    if not command:
        logger.error(f"Terminal execute called without pending command for run {run_id}")
        return {
            "pending_terminal": None,
            "phase": "executing",
        }

    logger.info(f"Executing terminal command for run {run_id}: {command[:50]}...")

    # Create tool call record
    tool_call = ExecutorToolCall(
        id=len(tool_history) + 1,
        tool="terminal",
        params={"command": command, "timeout": timeout},
        result=None,
        success=False,
        error=None,
    )

    try:
        # Execute command
        result = await execute_command(
            command=command,
            timeout=timeout,
            require_approval=False,  # Already approved
        )

        # Truncate output if needed
        output_limit = config.research.terminal_output_limit
        if len(result) > output_limit:
            result = result[:output_limit] + f"\n\n... (truncated, showing first {output_limit} chars)"

        tool_call["result"] = result
        tool_call["success"] = True

        logger.info(f"Terminal command succeeded for run {run_id}")

    except Exception as e:
        logger.error(f"Terminal command failed for run {run_id}: {e}")
        tool_call["error"] = str(e)
        tool_call["success"] = False

    return {
        "executor_tool_history": tool_call,  # Append via reducer
        "executor_call_count": 1,  # Increment via reducer
        "pending_terminal": None,
        "phase": "executing",
    }
