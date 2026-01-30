"""
Decision node - LLM decides which tool to use next or if done.

Uses structured output parsing for reliable decision extraction.
"""

import json
import logging
import re
from typing import Any

from backend.agents.state import ExecutorDecision, ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

DECISION_PROMPT = """You are an executor agent deciding which tool to use to gather information for a research task.

CURRENT TASK:
{task_description}

ORIGINAL QUERY:
{original_query}

PREVIOUS TOOL CALLS:
{tool_history}

ACCUMULATED RESULTS SO FAR:
{accumulated_results}

REMAINING CALLS: {remaining_calls}

AVAILABLE TOOLS:
1. web_search - Search the web for information. Params: {{"themes": ["query1", "query2", ...]}}
2. terminal - Execute a shell command (requires approval). Params: {{"command": "the command", "timeout": 60}}
3. read_file - Read a local file. Params: {{"path": "/path/to/file", "start_line": 1, "end_line": 100}}
4. knowledge - Answer from your own knowledge (use sparingly). Params: {{"answer": "your knowledge-based answer"}}

OUTPUT FORMAT (strict):
REASONING: <1-2 sentences explaining your choice>
DECISION: web_search | terminal | read_file | knowledge | DONE
PARAMS: <JSON object with tool parameters, or {{}} if DONE>

GUIDELINES:
- Prefer web_search for most information gathering
- Use terminal only when you need to run commands (e.g., check versions, run scripts)
- Use read_file when you need to examine specific local files
- Use knowledge only for well-established facts that don't need verification
- Choose DONE when you have gathered sufficient information for the task
- If previous tools failed, try alternative approaches

Respond with REASONING, DECISION, and PARAMS only."""


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


def _parse_decision_response(response: str) -> ExecutorDecision:
    """Parse the structured response from the LLM."""
    # Extract REASONING
    reasoning_match = re.search(r"REASONING:\s*(.+?)(?=\nDECISION:)", response, re.DOTALL)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else ""

    # Extract DECISION
    decision_match = re.search(r"DECISION:\s*(web_search|terminal|read_file|knowledge|DONE)", response, re.IGNORECASE)
    decision = decision_match.group(1).lower() if decision_match else "DONE"

    # Normalize DONE to uppercase
    if decision == "done":
        decision = "DONE"

    # Extract PARAMS
    params_match = re.search(r"PARAMS:\s*(\{.*\})", response, re.DOTALL)
    params = {}
    if params_match:
        try:
            params = json.loads(params_match.group(1))
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse PARAMS JSON: {params_match.group(1)}")
            params = {}

    return ExecutorDecision(
        reasoning=reasoning,
        decision=decision,
        params=params,
    )


async def decision_node(state: ResearchState) -> dict:
    """
    LLM-based decision maker that decides which tool to use next.

    Returns executor_decision with the chosen tool and parameters.

    Special case: If search_themes already exist in state (from theme_identifier
    or strategist), automatically decides to use web_search with those themes.
    """
    run_id = state.get("run_id", "")
    current_step = state.get("current_step_index", 0)
    plan = state.get("plan", [])
    original_query = state.get("original_query", "")
    tool_history = state.get("executor_tool_history", [])
    call_count = state.get("executor_call_count", 0)
    max_calls = state.get("max_executor_calls", 5)

    # Get current task description
    task_description = ""
    if current_step < len(plan):
        task_description = plan[current_step].get("description", "")

    remaining_calls = max_calls - call_count

    logger.info(f"Decision node for run {run_id}, step {current_step}, remaining calls: {remaining_calls}")

    # Check for pre-existing search_themes (from theme_identifier or strategist)
    # If this is the first call (no tool history) and themes exist, use them directly
    existing_themes = state.get("search_themes", [])
    if not tool_history and existing_themes:
        logger.info(f"Decision using pre-existing {len(existing_themes)} themes from theme_identifier/strategist")
        decision = ExecutorDecision(
            reasoning="Using search themes from theme_identifier/strategist",
            decision="web_search",
            params={"themes": existing_themes},
        )
        return {
            "executor_decision": decision,
        }

    # Build prompt
    prompt = DECISION_PROMPT.format(
        task_description=task_description,
        original_query=original_query,
        tool_history=_format_tool_history(tool_history),
        accumulated_results=_format_accumulated_results(tool_history),
        remaining_calls=remaining_calls,
    )

    # Call LLM
    llm = get_llm(temperature=0.3, run_id=run_id)
    response = await llm.ainvoke(prompt)

    # Parse response
    decision = _parse_decision_response(response.content)

    logger.info(f"Decision: {decision['decision']} - {decision['reasoning'][:100]}...")

    return {
        "executor_decision": decision,
    }
