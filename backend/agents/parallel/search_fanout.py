"""
Parallel search fan-out using LangGraph's Send API.

Enables concurrent execution of multiple search queries.
"""

import logging
from typing import Sequence

from langgraph.constants import Send

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


def fanout_searches(state: ResearchState) -> Sequence[Send] | str:
    """
    Conditional edge for search fan-out.

    Takes search_themes from state and creates a Send for each,
    enabling parallel execution of searches.

    Args:
        state: Current research state with search_themes populated

    Returns:
        - "merge_results" if no themes (skip search)
        - List of Send objects for parallel search execution
    """
    themes = state.get("search_themes", [])
    run_id = state.get("run_id", "")
    current_idx = state.get("current_step_index", 0)

    if not themes:
        logger.info(f"No search themes for run {run_id}, skipping to merge")
        return "merge_results"

    logger.info(f"Fanning out {len(themes)} searches for run {run_id}")

    # Create Send for each theme
    sends = []
    for theme in themes:
        sends.append(
            Send(
                "search_node",
                {
                    "query": theme,
                    "run_id": run_id,
                    "current_step_index": current_idx,
                },
            )
        )

    return sends
