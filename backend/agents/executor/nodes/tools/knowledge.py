"""
Knowledge node - uses LLM's built-in knowledge for answers.

Should be used sparingly for well-established facts.
"""

import logging

from backend.agents.state import ExecutorToolCall, ResearchState

logger = logging.getLogger(__name__)


async def knowledge_node(state: ResearchState) -> dict:
    """
    Record LLM knowledge-based answer as a tool result.

    The answer is provided in executor_decision params.
    """
    run_id = state.get("run_id", "")
    decision = state.get("executor_decision", {})
    params = decision.get("params", {})
    tool_history = state.get("executor_tool_history", [])

    answer = params.get("answer", "")

    logger.info(f"Knowledge node for run {run_id}: {answer[:100]}...")

    # Format the answer
    formatted_answer = f"Knowledge-based answer: {answer}"

    # Create tool call record
    tool_call = ExecutorToolCall(
        id=len(tool_history) + 1,
        tool="knowledge",
        params={"answer": answer[:200] + "..." if len(answer) > 200 else answer},
        result=formatted_answer,
        success=True,
        error=None,
    )

    return {
        "executor_tool_history": tool_call,  # Append via reducer
        "executor_call_count": 1,  # Increment via reducer
    }
