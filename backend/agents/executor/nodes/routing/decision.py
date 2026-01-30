"""
Decision node - LLM decides which tool to use next or if done.

Uses structured output for reliable decision extraction.
"""

import logging
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from backend.agents.state import ExecutorDecision, ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)


class BaseToolParams(BaseModel):
    """Base class for tool parameters."""

    pass


class WebSearchParams(BaseToolParams):
    """Parameters for web_search tool."""

    tool: Literal["web_search"] = "web_search"
    themes: list[str] = Field(description="List of search queries to execute")


class TerminalParams(BaseToolParams):
    """Parameters for terminal tool."""

    tool: Literal["terminal"] = "terminal"
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=60, description="Timeout in seconds")


class ReadFileParams(BaseToolParams):
    """Parameters for read_file tool."""

    tool: Literal["read_file"] = "read_file"
    path: str = Field(description="Path to the file to read")
    start_line: Optional[int] = Field(default=None, description="Starting line number")
    end_line: Optional[int] = Field(default=None, description="Ending line number")


class KnowledgeParams(BaseToolParams):
    """Parameters for knowledge tool."""

    tool: Literal["knowledge"] = "knowledge"
    answer: str = Field(description="Knowledge-based answer to provide")


ToolParams = Annotated[
    Union[WebSearchParams, TerminalParams, ReadFileParams, KnowledgeParams],
    Field(discriminator="tool"),
]


class ToolDecision(BaseModel):
    """Schema for tool decision response."""

    reasoning: str = Field(description="1-2 sentences explaining the choice")
    params: ToolParams = Field(description="Tool selection and its parameters")

DECISION_PROMPT = """You are an executor agent deciding which tool to use to gather information for a research task.

CURRENT TASK:
{task_description}

ORIGINAL QUERY:
{original_query}
{feedback_section}
PREVIOUS TOOL CALLS (this attempt):
{tool_history}

ACCUMULATED RESULTS SO FAR:
{accumulated_results}

REMAINING CALLS: {remaining_calls}

AVAILABLE TOOLS:
1. web_search - Search the web for information
2. terminal - Execute a shell command (requires approval)
3. read_file - Read a local file
4. knowledge - Answer from your own knowledge (use sparingly)

GUIDELINES:
- Prefer web_search for most information gathering
- Use terminal only when you need to run commands (e.g., check versions, run scripts)
- Use read_file when you need to examine specific local files
- Use knowledge only for well-established facts that don't need verification
- If you have feedback from a previous attempt, use it to guide your approach
- Always choose the most appropriate tool for the next step"""


def _format_tool_history(history: list[dict]) -> str:
    """Format tool history for the prompt."""
    if not history:
        return "(none)"

    lines = []
    for call in history:
        status = "SUCCESS" if call.get("success") else "FAILED"
        error = f" - Error: {call.get('error')}" if call.get("error") else ""
        result_preview = ""
        if call.get("result"):
            result_preview = call["result"][:200] + "..." if len(call["result"]) > 200 else call["result"]
        lines.append(
            f"- [{call.get('id', '?')}] {call.get('tool', 'unknown')}: {status}{error}\n  Params: {call.get('params', {})}\n  Result: {result_preview}"
        )
    return "\n".join(lines)


def _format_accumulated_results(history: list[dict]) -> str:
    """Format successful results from tool history."""
    if not history:
        return "(none yet)"

    successful = [h for h in history if h.get("success") and h.get("result")]
    if not successful:
        return "(no successful results yet)"

    lines = []
    for call in successful:
        result = call.get("result", "")
        preview = result[:500] + "..." if len(result) > 500 else result
        lines.append(f"[{call.get('tool', 'unknown')}]: {preview}")
    return "\n\n".join(lines)


def _extract_params(result: ToolDecision) -> dict:
    """Extract params dict from the tool params, excluding the discriminator field."""
    params = result.params.model_dump(exclude={"tool"})
    return params


async def decision_node(state: ResearchState) -> dict:
    """
    LLM-based decision maker that decides which tool to use next.

    Returns executor_decision with the chosen tool and parameters.

    If last_error contains feedback from a previous failed attempt (from strategist),
    it is included in the prompt to help guide the decision.
    """
    run_id = state.get("run_id", "")
    current_step = state.get("current_step_index", 0)
    plan = state.get("plan", [])
    original_query = state.get("original_query", "")
    tool_history = state.get("executor_tool_history", [])
    call_count = state.get("executor_call_count", 0)
    max_calls = state.get("max_executor_calls", 5)
    feedback = state.get("last_error")

    # Get current task description
    task_description = ""
    if current_step < len(plan):
        task_description = plan[current_step].get("description", "")

    remaining_calls = max_calls - call_count

    logger.info(
        f"[Iteration {call_count + 1}/{max_calls}] Decision node for run {run_id}, "
        f"step {current_step}, {remaining_calls} calls remaining"
    )

    # Build feedback section if we have feedback from a previous attempt
    feedback_section = ""
    if feedback:
        feedback_section = f"\nPREVIOUS ATTEMPT FEEDBACK:\n{feedback}\n"
        logger.info("Including feedback from previous attempt in decision prompt")

    # Build prompt
    prompt = DECISION_PROMPT.format(
        task_description=task_description,
        original_query=original_query,
        feedback_section=feedback_section,
        tool_history=_format_tool_history(tool_history),
        accumulated_results=_format_accumulated_results(tool_history),
        remaining_calls=remaining_calls,
    )

    # Call LLM with structured output
    llm = get_llm(temperature=0.3, run_id=run_id)
    structured_llm = llm.with_structured_output(ToolDecision)
    result: ToolDecision = await structured_llm.ainvoke(prompt)

    # Convert to ExecutorDecision format
    tool_choice = result.params.tool
    decision = ExecutorDecision(
        reasoning=result.reasoning,
        decision=tool_choice,
        params=_extract_params(result),
    )

    logger.info(
        f"[Iteration {call_count + 1}/{max_calls}] Decision: {tool_choice} - "
        f"{result.reasoning[:100]}..."
    )

    return {
        "executor_decision": decision,
    }
