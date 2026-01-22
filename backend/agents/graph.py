"""
Main research graph assembly.

Defines the StateGraph with all nodes and edges.
"""

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from backend.agents.state import ResearchState
from backend.agents.nodes import (
    planner_node,
    identify_themes_node,
    search_node,
    merge_results_node,
    evaluator_node,
    strategist_node,
    reporter_node,
)
from backend.agents.routing import route_search_fanout

logger = logging.getLogger(__name__)

# Global compiled graph cache
_compiled_graph = None


def build_research_graph() -> StateGraph:
    """
    Build the research StateGraph.

    Graph structure:
        START -> planner -> identify_themes -> search_fanout
                                                    |
                                            [parallel searches]
                                                    |
                                            merge_results -> evaluator
                                                                |
                                    +---------------------------+---------------------------+
                                    |                           |                           |
                            identify_themes              strategist                    reporter -> END
                            (next step)                 (recovery)
    """
    logger.info("Building research StateGraph")

    builder = StateGraph(ResearchState)

    # --- Add Nodes ---
    builder.add_node("planner", planner_node)
    builder.add_node("identify_themes", identify_themes_node)
    builder.add_node("search_node", search_node)
    builder.add_node("merge_results", merge_results_node)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("strategist", strategist_node)
    builder.add_node("reporter", reporter_node)

    # --- Add Edges ---

    # Start -> Planner
    builder.add_edge(START, "planner")

    # Planner routes via Command (already handled in node)
    # But we need a default edge for the builder
    builder.add_edge("planner", "identify_themes")

    # Identify themes -> search fanout (conditional)
    builder.add_conditional_edges(
        "identify_themes",
        route_search_fanout,
        # Map return values to node names
        {
            "merge_results": "merge_results",  # No themes case
            # Send objects handled automatically
        },
    )

    # Search node -> merge results (fan-in)
    builder.add_edge("search_node", "merge_results")

    # Merge results -> evaluator
    builder.add_edge("merge_results", "evaluator")

    # Evaluator routes via Command (to identify_themes, strategist, or reporter)
    # Default edge for builder structure
    builder.add_edge("evaluator", "identify_themes")

    # Strategist routes via Command (to identify_themes or reporter)
    builder.add_edge("strategist", "identify_themes")

    # Reporter -> END
    builder.add_edge("reporter", END)

    return builder


def create_research_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    interrupt_before: Optional[list[str]] = None,
    interrupt_after: Optional[list[str]] = None,
):
    """
    Create and compile the research graph.

    Args:
        checkpointer: LangGraph checkpointer for state persistence
        interrupt_before: Nodes to interrupt before (for human-in-the-loop)
        interrupt_after: Nodes to interrupt after

    Returns:
        Compiled StateGraph
    """
    builder = build_research_graph()

    # Default interrupts for human-in-the-loop
    if interrupt_before is None:
        interrupt_before = []

    if interrupt_after is None:
        # Interrupt after planner for plan review
        interrupt_after = ["planner"]

    logger.info(
        f"Compiling graph with checkpointer={checkpointer is not None}, "
        f"interrupt_before={interrupt_before}, interrupt_after={interrupt_after}"
    )

    compiled = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )

    return compiled


async def get_research_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    """
    Get or create the research graph.

    Uses a cached compiled graph if checkpointer hasn't changed.
    """
    global _compiled_graph

    # For now, always create new graph with provided checkpointer
    # In production, might want smarter caching
    _compiled_graph = create_research_graph(checkpointer=checkpointer)

    return _compiled_graph
