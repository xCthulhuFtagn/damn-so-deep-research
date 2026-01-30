"""
Main research graph assembly.

Defines the StateGraph with all nodes and edges.
"""

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from backend.agents.state import ResearchState
from backend.agents.planner import planner_node
from backend.agents.evaluator import evaluator_node
from backend.agents.strategist import strategist_node
from backend.agents.reporter import reporter_node
from backend.agents.routing import route_plan_approval
from backend.agents.executor.subgraph import build_executor_subgraph

logger = logging.getLogger(__name__)

# Global compiled graph cache
_compiled_graph = None


def build_research_graph() -> StateGraph:
    """
    Build the research StateGraph.

    Graph structure:
        START -> planner --[needs_replan?]--> planner (loop)
                    |
                    +--> executor (subgraph) -> evaluator
                              |                    |
                              |    +---------------+---------------+
                              |    |               |               |
                              +----+           strategist      reporter -> END
                           (next step)         (recovery)

    The executor subgraph includes:
    - search_themes: identifies search queries for current step
    - router: decides which tool to use
    - web_search (parallel search fanout)
    - terminal (with approval)
    - read_file
    - knowledge (LLM built-in)
    """
    logger.info("Building research StateGraph")

    builder = StateGraph(ResearchState)

    # Build and compile executor subgraph
    executor_subgraph = build_executor_subgraph().compile()

    # --- Add Nodes ---
    builder.add_node("planner", planner_node)
    builder.add_node("executor", executor_subgraph)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("strategist", strategist_node)
    builder.add_node("reporter", reporter_node)

    # --- Add Edges ---

    # Start -> Planner
    builder.add_edge(START, "planner")

    # Planner -> conditional routing based on plan approval
    # If needs_replan=True -> loop back to planner
    # If approved -> proceed to executor
    builder.add_conditional_edges(
        "planner",
        route_plan_approval,
        {
            "planner": "planner",
            "executor": "executor",
        },
    )

    # Executor -> evaluator
    builder.add_edge("executor", "evaluator")

    # Evaluator routes via Command (to executor, strategist, or reporter)
    # NO static edge here - Command.goto handles routing dynamically

    # Strategist routes via Command (to executor or reporter)
    # NO static edge here - Command.goto handles routing dynamically

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
