"""
Executor subgraph builder.

Assembles the executor subgraph with all nodes and edges.
"""

import logging

from langgraph.graph import StateGraph

from backend.agents.state import ResearchState
from backend.agents.executor.nodes import (
    # Lifecycle
    entry_node,
    exit_node,
    accumulator_node,
    # Routing
    decision_node,
    # Search workflow
    theme_identifier_node,
    search_dispatcher_node,
    search_worker_node,
    search_merger_node,
    # Tools
    terminal_prepare_node,
    terminal_execute_node,
    file_reader_node,
    knowledge_node,
)
from backend.agents.executor.routing import (
    route_decision,
    route_accumulator,
    executor_fanout_searches,
)

logger = logging.getLogger(__name__)


def build_executor_subgraph() -> StateGraph:
    """
    Build the executor subgraph.

    Graph structure:
        entry -> decision --[choice]--> web_search: theme_identifier -> search_dispatcher -> fanout -> search_worker -> search_merger -> accumulator
                     |                  terminal: terminal_prepare -> terminal_execute -> accumulator
                     |                  read_file: file_reader -> accumulator
                     |                  knowledge: knowledge -> accumulator
                     |                  DONE: exit
                     |
                     +<---- accumulator (loop if not done & < limit)
                                 |
                               exit -> (returns to parent graph)
    """
    logger.info("Building executor subgraph")

    builder = StateGraph(ResearchState)

    # --- Add Nodes ---
    # Lifecycle
    builder.add_node("entry", entry_node)
    builder.add_node("exit", exit_node)
    builder.add_node("accumulator", accumulator_node)

    # Routing
    builder.add_node("decision", decision_node)

    # Search workflow
    builder.add_node("theme_identifier", theme_identifier_node)
    builder.add_node("search_dispatcher", search_dispatcher_node)
    builder.add_node("search_worker", search_worker_node)
    builder.add_node("search_merger", search_merger_node)

    # Tools
    builder.add_node("terminal_prepare", terminal_prepare_node)
    builder.add_node("terminal_execute", terminal_execute_node)
    builder.add_node("file_reader", file_reader_node)
    builder.add_node("knowledge", knowledge_node)

    # --- Entry Point ---
    # NEW: entry → decision (decision sees feedback and picks tool)
    builder.set_entry_point("entry")
    builder.add_edge("entry", "decision")

    # --- Decision Conditional Edges ---
    # NEW: web_search path now goes through theme_identifier first
    builder.add_conditional_edges(
        "decision",
        route_decision,
        {
            "web_search": "theme_identifier",  # theme_id is AFTER decision
            "terminal": "terminal_prepare",
            "read_file": "file_reader",
            "knowledge": "knowledge",
            "exit": "exit",
        },
    )

    # --- Web Search Path ---
    # theme_identifier -> search_dispatcher -> fanout -> search_worker (parallel) -> search_merger -> accumulator
    builder.add_edge("theme_identifier", "search_dispatcher")
    builder.add_conditional_edges(
        "search_dispatcher",
        executor_fanout_searches,
        {
            "search_merger": "search_merger",
        },
    )
    builder.add_edge("search_worker", "search_merger")
    builder.add_edge("search_merger", "accumulator")

    # --- Terminal Path ---
    # terminal_prepare -> terminal_execute -> accumulator
    # Note: terminal_execute has an interrupt_before configured in parent graph
    builder.add_edge("terminal_prepare", "terminal_execute")
    builder.add_edge("terminal_execute", "accumulator")

    # --- Direct Tool Paths ---
    builder.add_edge("file_reader", "accumulator")
    builder.add_edge("knowledge", "accumulator")

    # --- Accumulator Loop ---
    builder.add_conditional_edges(
        "accumulator",
        route_accumulator,
        {
            "decision": "decision",
            "exit": "exit",
        },
    )

    # --- Exit Point ---
    builder.set_finish_point("exit")

    logger.info("Executor subgraph built successfully")

    return builder
