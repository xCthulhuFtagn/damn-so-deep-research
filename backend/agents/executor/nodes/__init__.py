"""
Executor subgraph node functions.

Organized into subdirectories by concern:
- lifecycle/: Graph control flow (entry, exit, accumulator)
- routing/: Decision making (decision)
- search/: Web search workflow (theme_identifier, dispatcher, worker, merger)
- tools/: Tool execution (terminal_prepare, terminal_execute, file_reader, knowledge)
"""

# Lifecycle nodes
from backend.agents.executor.nodes.lifecycle import (
    entry_node,
    exit_node,
    accumulator_node,
)

# Routing nodes
from backend.agents.executor.nodes.routing import decision_node

# Search workflow nodes
from backend.agents.executor.nodes.search import (
    theme_identifier_node,
    search_dispatcher_node,
    search_worker_node,
    search_merger_node,
)

# Tool execution nodes
from backend.agents.executor.nodes.tools import (
    terminal_prepare_node,
    terminal_execute_node,
    file_reader_node,
    knowledge_node,
)

__all__ = [
    # Lifecycle
    "entry_node",
    "exit_node",
    "accumulator_node",
    # Routing
    "decision_node",
    # Search workflow
    "theme_identifier_node",
    "search_dispatcher_node",
    "search_worker_node",
    "search_merger_node",
    # Tools
    "terminal_prepare_node",
    "terminal_execute_node",
    "file_reader_node",
    "knowledge_node",
]
