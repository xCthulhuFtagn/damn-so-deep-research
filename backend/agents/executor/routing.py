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

    Returns the tool node name or "exit" if DONE.
    """
    decision = state.get("executor_decision", {})
    choice = decision.get("decision", "DONE") if decision else "DONE"

    logger.debug(f"Routing decision: {choice}")

    if choice == "DONE":
        return "exit"

    # Map decision to node names (these match the subgraph.py conditional edge keys)
    tool_map = {
        "web_search": "web_search",
        "terminal": "terminal",
        "read_file": "read_file",
        "knowledge": "knowledge",
    }

    return tool_map.get(choice, "exit")


def route_accumulator(state: ResearchState) -> Literal["decision", "exit"]:
    """
    Decide whether to continue the loop or exit.

    Exits if:
    - Decision was DONE
    - Call limit reached
    """
    decision = state.get("executor_decision", {})
    call_count = state.get("executor_call_count", 0)
    max_calls = state.get("max_executor_calls", 5)

    # Check if LLM decided we're done
    if decision and decision.get("decision") == "DONE":
        logger.info("Accumulator: LLM decided DONE, exiting")
        return "exit"

    # Check call limit
    if call_count >= max_calls:
        logger.info(f"Accumulator: Call limit reached ({call_count}/{max_calls}), exiting")
        return "exit"

    logger.debug(f"Accumulator: Continuing loop ({call_count}/{max_calls} calls)")
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
