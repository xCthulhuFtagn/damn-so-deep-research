"""
Strategist node - recovery from failed executor attempts.

Generates structured feedback for the executor based on previous failed attempts.
Does NOT create new plan steps - works within the current step's substep budget.
"""

import logging
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.types import Command

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

STRATEGIST_PROMPT = """You are a Recovery Strategist for a research system.

An execution attempt has failed evaluation. Your job is to analyze WHY the attempt failed
and provide strategic guidance for a different approach.

ORIGINAL RESEARCH QUERY:
{original_query}

CURRENT TASK:
{step_description}

EVALUATION ERROR:
{error}

TOOLS USED IN THIS ATTEMPT:
{tool_history}

PARTIAL FINDINGS COLLECTED:
{partial_findings}

YOUR TASK:
Analyze why the combination of tools and approaches failed to satisfy the task.
Provide clear, actionable guidance on what to try differently.

OUTPUT FORMAT:
Write a brief analysis (2-4 sentences) explaining:
1. What the previous attempt tried and why it didn't work
2. What different approach or tools should be tried next

Be specific and strategic. Focus on WHAT to do differently, not just "try harder"."""


def _format_tool_history_for_feedback(tool_history: list[dict]) -> str:
    """Format tool history into a readable summary for feedback."""
    if not tool_history:
        return "(no tools were used)"

    lines = []
    for call in tool_history:
        tool = call.get("tool", "unknown")
        params = call.get("params", {})
        success = call.get("success", False)
        status = "SUCCESS" if success else "FAILED"

        # Format based on tool type
        if tool == "web_search":
            themes = params.get("themes", [])
            lines.append(f"- web_search: queries={themes} [{status}]")
        elif tool == "knowledge":
            answer = params.get("answer", call.get("result", ""))
            truncated = answer[:100] + "..." if len(answer) > 100 else answer
            lines.append(f"- knowledge: (answer: {truncated}) [{status}]")
        elif tool == "terminal":
            cmd = params.get("command", "")
            lines.append(f"- terminal: command=\"{cmd}\" [{status}]")
        elif tool == "read_file":
            path = params.get("path", "")
            lines.append(f"- read_file: path=\"{path}\" [{status}]")
        else:
            lines.append(f"- {tool}: {params} [{status}]")

    return "\n".join(lines) if lines else "(no tools were used)"


async def strategist_node(
    state: ResearchState,
) -> Command[Literal["executor", "reporter"]]:
    """
    Recovery strategist - generates structured feedback for executor retry.

    Analyzes the previous failed attempt and generates feedback that includes:
    - Clear header indicating this is from a PREVIOUS execution cycle
    - Summary of tools used in the failed attempt
    - LLM analysis of why the attempt failed and what to try differently

    The feedback is stored in `last_error` for the decision node to use.
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]
    error = state.get("last_error", "Unknown error")
    tool_history = state.get("executor_tool_history", [])

    logger.info(f"Strategist for run {run_id}, step {current_idx}")

    if current_idx >= len(plan):
        logger.warning("Invalid step index, moving to reporter")
        return Command(
            update={"phase": "reporting"},
            goto="reporter",
        )

    current_step = plan[current_idx]
    accumulated = current_step.get("accumulated_findings", [])

    # Format tool history for the prompt
    tool_history_text = _format_tool_history_for_feedback(tool_history)

    partial_text = (
        "\n".join(accumulated[:5]) if accumulated else "No partial findings yet"
    )

    # Generate strategic feedback using LLM
    llm = get_llm(temperature=0.5)
    messages = [
        SystemMessage(
            content=STRATEGIST_PROMPT.format(
                original_query=state["original_query"],
                step_description=current_step["description"],
                error=error,
                tool_history=tool_history_text,
                partial_findings=partial_text,
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    analysis = response.content.strip()

    logger.info(f"Generated strategic feedback for retry: {analysis[:100]}...")

    # Build structured feedback for the decision node
    feedback = f"""Note: This feedback is from a PREVIOUS execution cycle that was evaluated and rejected.
You are now starting a fresh attempt. Use this feedback to try a different approach.

TASK: {current_step['description']}

TOOLS USED IN PREVIOUS ATTEMPT:
{tool_history_text}

WHY IT FAILED:
{analysis}"""

    # Route back to executor with feedback in last_error
    # Clear tool history and search_themes for fresh attempt
    return Command(
        update={
            "last_error": feedback,
            "phase": "executing",
            "step_findings": [],  # Clear for new attempt
            "search_themes": [],  # Clear - decision will pick new approach
            "executor_tool_history": [],  # Clear for fresh attempt
            "executor_call_count": 0,  # Reset call count
        },
        goto="executor",
    )
