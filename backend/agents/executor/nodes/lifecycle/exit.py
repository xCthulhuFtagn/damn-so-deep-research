"""
Exit node - prepares findings for the evaluator.

Filters successful results and formats them for step_findings.
"""

import logging

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def exit_node(state: ResearchState) -> dict:
    """
    Prepare executor results for the evaluator.

    - Filters to successful tool results only
    - Formats findings for step_findings
    - Clears executor state fields
    """
    run_id = state.get("run_id", "")
    tool_history = state.get("executor_tool_history", [])
    call_count = state.get("executor_call_count", 0)

    logger.info(f"Executor exit for run {run_id}, {call_count} calls made")

    # Filter to successful results
    successful_results = [
        call for call in tool_history
        if call.get("success") and call.get("result")
    ]

    # Build step_findings from successful results
    findings = []

    if successful_results:
        for call in successful_results:
            tool = call.get("tool", "unknown")
            result = call.get("result", "")
            findings.append(f"[{tool}] {result}")

        logger.info(f"Executor produced {len(findings)} findings from {len(successful_results)} successful calls")
    else:
        # All tools failed - report errors
        errors = []
        for call in tool_history:
            if call.get("error"):
                errors.append(f"{call.get('tool', 'unknown')}: {call.get('error')}")

        if errors:
            findings.append(f"All tool attempts failed: {'; '.join(errors)}")
        else:
            findings.append("No tool results available.")

        logger.warning(f"Executor exit with no successful results for run {run_id}")

    return {
        "step_findings": findings,
        # Clear executor state for next step
        "executor_tool_history": None,  # Reset via reducer
        "executor_call_count": 0,  # Reset
        "executor_decision": None,
        "pending_terminal": None,
        "phase": "evaluating",
    }
