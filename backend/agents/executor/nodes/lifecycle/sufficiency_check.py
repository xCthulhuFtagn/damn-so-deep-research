"""
Sufficiency check node - LLM evaluates if gathered information is enough.

After at least 1 tool has been called, this node asks the LLM whether
the accumulated information is sufficient to complete the current task,
or if more tool calls are needed.
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)


class SufficiencyDecision(BaseModel):
    """Schema for sufficiency check response."""

    reasoning: str = Field(
        description="Brief explanation of why the information is or isn't sufficient"
    )
    decision: Literal["SUFFICIENT", "CONTINUE"] = Field(
        description="SUFFICIENT if enough info gathered, CONTINUE if more tools needed"
    )


SUFFICIENCY_PROMPT = """You are evaluating whether enough information has been gathered to complete a research task.

CURRENT TASK:
{task_description}

ORIGINAL QUERY:
{original_query}

TOOL CALLS MADE ({call_count} total):
{tool_history}

ACCUMULATED RESULTS:
{accumulated_results}

REMAINING CALLS BUDGET: {remaining_calls}

Decide whether to stop or continue:
- SUFFICIENT: We have gathered enough information to meaningfully address this task. No more tool calls needed.
- CONTINUE: We need more information. Additional tool calls would be valuable.

Guidelines:
- If the results contain substantial, relevant information that addresses the task, choose SUFFICIENT.
- If results are thin, missing key aspects, or the task requires more data, choose CONTINUE.
- Consider the remaining call budget - if low, lean toward SUFFICIENT if results are reasonable.
- Don't be overly perfectionist - "good enough" is acceptable."""


def _format_tool_history_detailed(history: list[dict]) -> str:
    """Format tool history with full details for sufficiency evaluation."""
    if not history:
        return "(no tools called yet)"

    lines = []
    for call in history:
        status = "SUCCESS" if call.get("success") else "FAILED"
        result = call.get("result", "")
        # Show more result content for sufficiency evaluation
        result_preview = result[:1000] + "..." if len(result) > 1000 else result
        lines.append(
            f"[{call.get('id', '?')}] {call.get('tool', 'unknown')} ({status}):\n"
            f"  Params: {call.get('params', {})}\n"
            f"  Result: {result_preview}"
        )
    return "\n\n".join(lines)


def _format_accumulated_results_detailed(history: list[dict]) -> str:
    """Format all successful results for sufficiency evaluation."""
    if not history:
        return "(none)"

    successful = [h for h in history if h.get("success") and h.get("result")]
    if not successful:
        return "(no successful results)"

    lines = []
    for call in successful:
        result = call.get("result", "")
        # Show substantial portion for evaluation
        preview = result[:2000] + "..." if len(result) > 2000 else result
        lines.append(f"[{call.get('tool', 'unknown')}]:\n{preview}")
    return "\n\n---\n\n".join(lines)


async def sufficiency_check_node(state: ResearchState) -> dict:
    """
    Evaluate if gathered information is sufficient to complete the task.

    Handles exit conditions:
    - Call limit reached (immediate exit, no LLM call)
    - LLM determines info is sufficient (after 1+ tool calls)

    Sets 'executor_sufficient' flag in state to indicate the decision.
    """
    run_id = state.get("run_id", "")
    call_count = state.get("executor_call_count", 0)
    max_calls = state.get("max_executor_calls", 5)
    tool_history = state.get("executor_tool_history", [])
    current_step = state.get("current_step_index", 0)
    plan = state.get("plan", [])
    original_query = state.get("original_query", "")

    # Get current task description
    task_description = ""
    if current_step < len(plan):
        task_description = plan[current_step].get("description", "")

    remaining_calls = max_calls - call_count

    logger.info(
        f"[Iteration {call_count}] Sufficiency check for run {run_id}, "
        f"step {current_step}, {call_count} tools called, {remaining_calls} remaining"
    )

    # Check call limit
    if call_count >= max_calls:
        logger.info(f"[Iteration {call_count}] Call limit reached ({call_count}/{max_calls}), marking sufficient")
        return {"executor_sufficient": True}

    # If no tools called yet, skip LLM sufficiency check - we need at least one tool call
    if call_count < 1:
        logger.debug("No tools called yet, skipping LLM sufficiency check")
        return {"executor_sufficient": False}

    # Build prompt
    prompt = SUFFICIENCY_PROMPT.format(
        task_description=task_description,
        original_query=original_query,
        call_count=call_count,
        tool_history=_format_tool_history_detailed(tool_history),
        accumulated_results=_format_accumulated_results_detailed(tool_history),
        remaining_calls=remaining_calls,
    )

    # Call LLM with structured output
    llm = get_llm(temperature=0.1, run_id=run_id)
    structured_llm = llm.with_structured_output(SufficiencyDecision)
    result: SufficiencyDecision = await structured_llm.ainvoke(prompt)

    is_sufficient = result.decision == "SUFFICIENT"

    logger.info(
        f"[Iteration {call_count}] Sufficiency decision: {result.decision} - "
        f"{result.reasoning[:100]}..."
    )

    return {"executor_sufficient": is_sufficient}
