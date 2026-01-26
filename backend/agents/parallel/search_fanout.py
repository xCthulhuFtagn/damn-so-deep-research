"""
Parallel search fan-out using LangGraph's Send API.

Enables concurrent execution of multiple search queries.
"""

import logging
from typing import Sequence

from langgraph.constants import Send

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


def fanout_searches(state: ResearchState) -> Sequence[Send]:
    """
    Fan-out to parallel search nodes.

    Takes search_themes from state and creates a Send for each,
    enabling parallel execution of searches.

    Args:
        state: Current research state with search_themes populated

    Returns:
        List of Send objects, one per search theme
    """
    themes = state.get("search_themes", [])
    run_id = state.get("run_id", "")
    current_idx = state.get("current_step_index", 0)

    if not themes:
        logger.warning(f"No search themes for run {run_id}")
        # Return empty list - will trigger merge_results directly
        return []

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
