"""
Routing functions for conditional edges in the research graph.
"""

import logging
from typing import Literal, Sequence

from langgraph.constants import Send

from backend.agents.state import ResearchState
from backend.agents.parallel.search_fanout import fanout_searches

logger = logging.getLogger(__name__)


def route_after_planning(
    state: ResearchState,
) -> Literal["identify_themes", "__end__"]:
    """
    Route after planning phase.

    If plan is empty, end. Otherwise, start execution.
    """
    if not state.get("plan"):
        logger.warning("Empty plan, ending graph")
        return "__end__"
    return "identify_themes"


def route_after_search(
    state: ResearchState,
) -> Literal["evaluator", "identify_themes"]:
    """
    Route after search results are merged.

    Always routes to evaluator to assess findings.
    """
    return "evaluator"


def route_search_fanout(state: ResearchState) -> Sequence[Send] | str:
    """
    Conditional edge for search fan-out.

    If needs_replan is True, route back to planner.
    If themes exist, fan out to parallel searches.
    If no themes, skip to merge (which will be empty).
    """
    # Check for replan request first
    if state.get("needs_replan", False):
        logger.info("Routing back to planner for re-planning")
        return "planner"

    themes = state.get("search_themes", [])

    if not themes:
        # No themes - go directly to merge_results
        return "merge_results"

    # Fan out to parallel searches
    return fanout_searches(state)


def should_continue_research(
    state: ResearchState,
) -> Literal["identify_themes", "reporter"]:
    """
    Check if there are more steps to process.
    """
    plan = state.get("plan", [])
    todo_steps = [s for s in plan if s["status"] == "TODO"]

    if todo_steps:
        return "identify_themes"
    return "reporter"
