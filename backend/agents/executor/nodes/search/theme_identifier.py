"""
Theme identifier node - identifies search themes for the current plan step.

Analyzes the current plan step and determines what to search for.
This is the first step in the executor subgraph.
"""

import logging

from langchain_core.messages import SystemMessage

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


async def theme_identifier_node(state: ResearchState) -> dict:
    """
    Identifies search themes for the current plan step.

    This is the first node in the executor subgraph, replacing the
    old identify_themes node from the main graph.

    Handles:
    - Finding current step (IN_PROGRESS or first TODO)
    - Using strategist-provided themes if available (recovery scenario)
    - Generating new themes via LLM
    - Marking step as IN_PROGRESS
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]

    logger.info(f"Theme identifier for run {run_id}, step {current_idx}")

    # Check if we have more steps to process
    todo_steps = [s for s in plan if s["status"] == "TODO"]
    if not todo_steps:
        logger.info("No more TODO steps")
        return {
            "search_themes": [],
            "phase": "reporting",
        }

    # Get current step - check for IN_PROGRESS first (recovery scenario)
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
            "search_themes": [],
            "phase": "reporting",
        }

    # Check if strategist already provided search_themes (recovery scenario)
    existing_themes = state.get("search_themes", [])
    if existing_themes and current_step["status"] == "IN_PROGRESS":
        # Strategist already generated alternative queries - use them directly
        logger.info(
            f"Using {len(existing_themes)} themes from strategist: {existing_themes}"
        )
        return {
            "current_step_index": current_idx,
            "step_findings": [],
            "step_search_count": 0,
            "phase": "executing",
            # search_themes already set by strategist
        }

    # Mark step as in progress (if not already)
    updated_plan = plan.copy()
    if current_step["status"] == "TODO":
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

    return {
        "plan": updated_plan,
        "current_step_index": current_idx,
        "search_themes": themes,
        "step_findings": [],
        "step_search_count": 0,
        "phase": "executing",
    }
