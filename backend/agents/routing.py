"""
Routing functions for conditional edges in the research graph.
"""

import logging
from typing import Literal

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


def route_plan_approval(state: ResearchState) -> Literal["planner", "executor"]:
    """
    Route after planner node based on plan approval status.

    If user requested re-planning (needs_replan=True) -> back to planner.
    If plan is approved -> proceed to executor.
    """
    if state.get("needs_replan", False):
        logger.info("Plan rejected, routing back to planner for re-planning")
        return "planner"

    logger.info("Plan approved, proceeding to executor")
    return "executor"


