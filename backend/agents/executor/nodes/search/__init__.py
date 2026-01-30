"""
Search nodes - web search workflow pipeline.

- theme_identifier: Identifies search queries for the current plan step
- dispatcher: Prepares search themes for parallel fanout
- worker: Executes a single search query (parallel via Send API)
- merger: Merges parallel search results
"""

from backend.agents.executor.nodes.search.theme_identifier import theme_identifier_node
from backend.agents.executor.nodes.search.dispatcher import search_dispatcher_node
from backend.agents.executor.nodes.search.worker import search_worker_node
from backend.agents.executor.nodes.search.merger import search_merger_node

__all__ = [
    "theme_identifier_node",
    "search_dispatcher_node",
    "search_worker_node",
    "search_merger_node",
]
