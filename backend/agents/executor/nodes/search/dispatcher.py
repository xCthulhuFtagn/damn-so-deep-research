"""
Search dispatcher node - prepares web search for parallel fanout.

Extracts themes from executor decision and sets up for fanout_searches.
"""

import logging

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def search_dispatcher_node(state: ResearchState) -> dict:
    """
    Prepare web search by setting search_themes from executor decision.

    The actual fanout happens via fanout_searches conditional edge,
    which creates Send() objects for parallel search execution.

    Themes are sourced from (in priority order):
    1. executor_decision.params.themes (from decision node)
    2. state.search_themes (from theme_identifier or strategist)
    """
    run_id = state.get("run_id", "")
    decision = state.get("executor_decision", {})
    params = decision.get("params", {}) if decision else {}

    # Extract themes from decision params
    themes = params.get("themes", [])

    # Handle case where single query is provided instead of list
    if not themes and params.get("query"):
        themes = [params.get("query")]

    # Fall back to existing search_themes from state (set by theme_identifier or strategist)
    if not themes:
        themes = state.get("search_themes", [])

    # Ensure we have at least one theme
    if not themes:
        logger.warning(f"Search dispatcher called without themes for run {run_id}")
        themes = []

    logger.info(f"Search dispatcher preparing {len(themes)} themes for run {run_id}: {themes}")

    return {
        "search_themes": themes,
        "step_search_count": 0,  # Reset before parallel execution
        "phase": "searching",
    }
