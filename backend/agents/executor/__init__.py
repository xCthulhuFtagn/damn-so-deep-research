"""
Executor subgraph for flexible multi-tool research execution.

Supports web search, terminal commands, file reading, and LLM knowledge
with an iterative loop and configurable call limit.
"""

from backend.agents.executor.subgraph import build_executor_subgraph

__all__ = ["build_executor_subgraph"]
