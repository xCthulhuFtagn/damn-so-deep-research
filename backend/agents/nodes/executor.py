"""
Executor node - identifies search themes for the current step.

Analyzes the current plan step and determines what to search for.
"""

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.types import Command

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

THEME_IDENTIFICATION_PROMPT = """You are a research assistant identifying search themes.

Given a research task, identify 1-3 specific search queries that would help complete this task.
Each query should target a different aspect or source of information.

OUTPUT FORMAT:
Output each search query on a separate line, prefixed with "SEARCH:":
SEARCH: [first search query]
SEARCH: [second search query]
SEARCH: [third search query]

Be specific and targeted. Good queries are:
- Focused on a single concept
- Include relevant keywords
- Avoid overly broad terms

IMPORTANT: Output ONLY the search queries in the format above. No other text."""


def parse_search_themes(content: str) -> list[str]:
    """Parse search queries from LLM response."""
    themes = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("SEARCH:"):
            query = line[7:].strip()
            if query:
                themes.append(query)
    return themes


async def identify_themes_node(
    state: ResearchState,
) -> dict:
    """
    Identifies search themes for the current plan step.

    Returns state updates. Routing is handled by conditional edges:
    - If search_themes is populated -> route_search_fanout fans out to search_node
    - If search_themes is empty -> routes to merge_results
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]

    logger.info(f"Identify themes for run {run_id}, step {current_idx}")

    # Check if we have more steps to process
    todo_steps = [s for s in plan if s["status"] == "TODO"]
    if not todo_steps:
        logger.info("No more TODO steps, clearing themes for routing")
        # Empty themes will route to merge_results via conditional edge
        return {
            "search_themes": [],
            "phase": "reporting",
        }

    # Get current step
    current_step = None
    for i, step in enumerate(plan):
        if step["status"] == "TODO":
            current_step = step
            current_idx = i
            break

    if not current_step:
        logger.info("No TODO steps found, clearing themes for routing")
        return {
            "search_themes": [],
            "phase": "reporting",
        }

    # Mark step as in progress
    updated_plan = plan.copy()
    updated_plan[current_idx] = {**current_step, "status": "IN_PROGRESS"}

    # Identify search themes
    llm = get_llm(temperature=0.0)

    messages = [
        SystemMessage(content=THEME_IDENTIFICATION_PROMPT),
        SystemMessage(content=f"Research task: {current_step['description']}"),
    ]

    response = await llm.ainvoke(messages)
    themes = parse_search_themes(response.content)

    if not themes:
        # Fallback: use the step description as a single query
        themes = [current_step["description"]]

    # Limit to max 3 themes
    themes = themes[:3]

    logger.info(f"Identified {len(themes)} search themes: {themes}")

    # Return state update - conditional edge (route_search_fanout) handles routing
    return {
        "plan": updated_plan,
        "current_step_index": current_idx,
        "search_themes": themes,
        "step_findings": [],
        "step_search_count": 0,
        "phase": "searching",
    }


async def executor_node(state: ResearchState) -> dict:
    """
    Legacy executor node - now just calls identify_themes.

    Kept for compatibility with existing code references.
    """
    # This is now handled by identify_themes_node and parallel search
    raise NotImplementedError(
        "Use identify_themes_node instead. The executor flow is now: "
        "identify_themes -> search_fanout -> merge_results -> evaluator"
    )
