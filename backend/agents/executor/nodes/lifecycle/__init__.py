"""
Lifecycle nodes - control the executor subgraph flow.

- entry: Resets state at the start of execution
- exit: Prepares findings for the evaluator
- accumulator: Collects tool results and controls the loop
"""

from backend.agents.executor.nodes.lifecycle.entry import entry_node
from backend.agents.executor.nodes.lifecycle.exit import exit_node
from backend.agents.executor.nodes.lifecycle.accumulator import accumulator_node

__all__ = [
    "entry_node",
    "exit_node",
    "accumulator_node",
]
