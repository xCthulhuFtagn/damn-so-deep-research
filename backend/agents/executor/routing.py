"""
Routing functions for the executor subgraph.

Conditional edge functions for tool routing and loop control.
"""

import logging
from typing import Literal, Sequence

from langgraph.constants import Send

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


def route_decision(state: ResearchState) -> str:
    """
    Route based on decision node's tool choice.

    Returns the tool node name. Decision node always picks a tool,
    sufficiency_check handles the exit decision.
    """
    decision = state.get("executor_decision", {})
    choice = decision.get("decision", "web_search") if decision else "web_search"

    logger.debug(f"Routing decision: {choice}")

    # Map decision to node names (these match the subgraph.py conditional edge keys)
    tool_map = {
        "web_search": "web_search",
        "terminal": "terminal",
        "read_file": "read_file",
        "knowledge": "knowledge",
    }

    return tool_map.get(choice, "web_search")


def route_sufficiency_check(state: ResearchState) -> Literal["decision", "exit"]:
    """
    Route based on sufficiency check result.

    Exits if LLM determined we have sufficient information
    (or call limit was reached, checked in sufficiency_check_node).

    Otherwise, continue to decision for more tool calls.
    """
    is_sufficient = state.get("executor_sufficient", False)
    call_count = state.get("executor_call_count", 0)
    max_calls = state.get("max_executor_calls", 5)

    if is_sufficient:
        logger.info(f"[Iteration {call_count}] Sufficiency check: SUFFICIENT, exiting loop")
        return "exit"

    logger.debug(f"[Iteration {call_count}] Sufficiency check: CONTINUE ({call_count}/{max_calls} calls)")
    return "decision"


def executor_fanout_searches(state: ResearchState) -> Sequence[Send] | str:
    """
    Fan-out for web searches within executor subgraph.

    Similar to the parent graph's fanout_searches but routes
    to search_merger within the executor.
    """
    themes = state.get("search_themes", [])
    run_id = state.get("run_id", "")

    if not themes:
        logger.info(f"No search themes for executor fanout in run {run_id}")
        return "search_merger"

    logger.info(f"Executor fanning out {len(themes)} searches for run {run_id}")

    sends = []
    for theme in themes:
        sends.append(
            Send(
                "search_worker",
                {
                    "query": theme,
                    "run_id": run_id,
                },
            )
        )

    return sends
