"""
Entry node - resets executor state at the start of each subgraph invocation.
"""

import logging

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def entry_node(state: ResearchState) -> dict:
    """
    Reset executor state at the beginning of executor subgraph.

    Clears tool history and call count for a fresh execution cycle.
    """
    run_id = state.get("run_id", "")
    current_step = state.get("current_step_index", 0)
    plan = state.get("plan", [])

    step_desc = ""
    if current_step < len(plan):
        step_desc = plan[current_step].get("description", "")

    logger.info(
        f"Executor entry for run {run_id}, step {current_step}: {step_desc[:50]}..."
    )

    return {
        "executor_tool_history": None,  # Reset signal
        "executor_call_count": 0,  # Reset count
        "executor_decision": None,
        "pending_terminal": None,
        "phase": "executing",
    }
