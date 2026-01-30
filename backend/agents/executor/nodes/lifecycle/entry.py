"""
Entry node - initializes executor state and discovers current step.

This is the first node in the executor subgraph. It handles:
- Finding the current step (IN_PROGRESS or first TODO)
- Marking the step as IN_PROGRESS
- Preserving last_error feedback from strategist for decision node
"""

import logging

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def entry_node(state: ResearchState) -> dict:
    """
    Initialize executor state and discover current step.

    Handles step discovery (previously in theme_identifier) and
    preserves feedback from strategist (last_error) for decision node.
    """
    run_id = state.get("run_id", "")
    plan = state.get("plan", [])
    current_idx = state.get("current_step_index", 0)

    # Check if we have more steps to process
    todo_steps = [s for s in plan if s["status"] == "TODO"]
    in_progress_steps = [s for s in plan if s["status"] == "IN_PROGRESS"]

    if not todo_steps and not in_progress_steps:
        logger.info("No more TODO/IN_PROGRESS steps")
        return {
            "phase": "reporting",
        }

    # Get current step - check for IN_PROGRESS first (recovery/retry scenario)
    current_step = None
    for i, step in enumerate(plan):
        if step["status"] == "IN_PROGRESS":
            current_step = step
            current_idx = i
            break

    # If no IN_PROGRESS step, find first TODO
    if not current_step:
        for i, step in enumerate(plan):
            if step["status"] == "TODO":
                current_step = step
                current_idx = i
                break

    if not current_step:
        logger.info("No TODO/IN_PROGRESS steps found")
        return {
            "phase": "reporting",
        }

    # Mark step as in progress (if not already)
    updated_plan = None
    if current_step["status"] == "TODO":
        updated_plan = plan.copy()
        updated_plan[current_idx] = {**current_step, "status": "IN_PROGRESS"}

    step_desc = current_step.get("description", "")
    logger.info(
        f"Executor entry for run {run_id}, step {current_idx}: {step_desc[:50]}..."
    )

    # Build return state
    # Note: last_error is preserved for decision node to use (from strategist feedback)
    result = {
        "current_step_index": current_idx,
        "executor_decision": None,
        "pending_terminal": None,
        "phase": "executing",
        "step_findings": [],
        "step_search_count": 0,
    }

    # Only reset executor state if NOT coming from strategist retry
    # (strategist already resets these in its Command)
    has_feedback = state.get("last_error") is not None
    if not has_feedback:
        result["executor_tool_history"] = None  # Reset signal
        result["executor_call_count"] = 0

    if updated_plan:
        result["plan"] = updated_plan

    return result
