"""
Strategist node - recovery from failed steps.

Analyzes failures and inserts corrective steps into the plan.
"""

import logging
import re
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.types import Command

from backend.agents.state import PlanStep, ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

STRATEGIST_PROMPT = """You are a Recovery Strategist for a research system.

A research step has FAILED. Your job is to create corrective steps to recover.

ORIGINAL QUERY:
{original_query}

FAILED STEP:
{failed_step}

ERROR/REASON:
{error}

COMPLETED STEPS SO FAR:
{completed_steps}

SYSTEM CAPABILITIES:
- The system ONLY has access to a web search tool (Firecrawl).
- It CANNOT download PDF files, access local libraries, or browse physical archives.
- It CANNOT execute arbitrary code or local file operations.
- It can only read text content available directly on web pages.

YOUR TASK:
Create 1-3 corrective steps that will help recover from this failure.
These steps should:
1. Try alternative search queries to get the needed information.
2. Break down the failed task into smaller, more specific queries.
3. Look for summaries, excerpts, or analyses if full texts are not available.

NAMING CONVENTION:
Each corrective step MUST be named: "Recovery: [specific search-focused action]"

OUTPUT FORMAT:
Output each corrective step on a separate line:
1. Recovery: [first corrective search action]
2. Recovery: [second corrective search action]

FORBIDDEN:
- Do NOT suggest "Download PDF" or "Save file".
- Do NOT suggest "Search locally" or "Check local database".
- Do NOT repeat the exact same failed task.
- Do NOT add reporting or summarization steps."""


def parse_corrective_steps(content: str) -> list[str]:
    """Parse corrective steps from strategist response."""
    steps = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Match numbered format
        match = re.match(r"^\d+[\.\)]\s*(.+)$", line)
        if match:
            steps.append(match.group(1).strip())
            continue

        # Match bullet format
        match = re.match(r"^[\-\*]\s*(.+)$", line)
        if match:
            steps.append(match.group(1).strip())
            continue

        # Match lines starting with "Recovery:"
        if line.lower().startswith("recovery:"):
            steps.append(line)

    return steps


async def strategist_node(
    state: ResearchState,
) -> Command[Literal["identify_themes", "reporter"]]:
    """
    Recovery strategist - creates corrective steps after failure.

    Inserts new steps after the failed step and routes back to execution.
    """
    run_id = state["run_id"]
    plan = state["plan"]
    failed_idx = state.get("failed_step_id")
    error = state.get("last_error", "Unknown error")
    recovery_attempts = state.get("recovery_attempts", 0)

    logger.info(f"Strategist for run {run_id}, failed step {failed_idx}")

    # Limit recovery attempts
    if recovery_attempts >= 2:
        logger.warning("Max recovery attempts reached, moving to reporter")
        return Command(
            update={
                "phase": "reporting",
                "recovery_attempts": 0,
            },
            goto="reporter",
        )

    if failed_idx is None or failed_idx >= len(plan):
        logger.warning("Invalid failed step index")
        return Command(
            update={"phase": "reporting"},
            goto="reporter",
        )

    failed_step = plan[failed_idx]

    # Build context
    completed = [
        f"- {s['description']}: {s.get('result', 'No result')[:100]}"
        for s in plan
        if s["status"] == "DONE"
    ]
    completed_text = "\n".join(completed) if completed else "None"

    # Generate corrective steps
    llm = get_llm(temperature=0.3)  # Slight creativity for alternatives
    messages = [
        SystemMessage(
            content=STRATEGIST_PROMPT.format(
                original_query=state["original_query"],
                failed_step=failed_step["description"],
                error=error,
                completed_steps=completed_text,
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    corrective_steps = parse_corrective_steps(response.content)

    if not corrective_steps:
        # Fallback: simple retry with modified query
        corrective_steps = [
            f"Recovery: Alternative search for {failed_step['description']}"
        ]

    logger.info(f"Generated {len(corrective_steps)} corrective steps")

    # Insert corrective steps into plan after failed step
    updated_plan = plan.copy()

    # Find the highest existing ID
    max_id = max(s["id"] for s in plan) if plan else -1

    # Create new PlanStep objects
    new_steps = [
        PlanStep(
            id=max_id + i + 1,
            description=desc,
            status="TODO",
            result=None,
            error=None,
        )
        for i, desc in enumerate(corrective_steps)
    ]

    # Insert after failed step
    insert_pos = failed_idx + 1
    updated_plan = (
        updated_plan[:insert_pos] + new_steps + updated_plan[insert_pos:]
    )

    logger.info(f"Plan updated: {len(updated_plan)} total steps")

    return Command(
        update={
            "plan": updated_plan,
            "current_step_index": insert_pos,  # Start from first corrective step
            "phase": "identifying_themes",
            "failed_step_id": None,
            "last_error": None,
            "recovery_attempts": recovery_attempts + 1,
            "step_findings": [],
        },
        goto="identify_themes",
    )
