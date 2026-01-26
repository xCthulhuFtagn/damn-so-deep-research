"""
Agent node functions for the research graph.

Each node is an async function that takes ResearchState and returns
either an update dict or a Command for state update + routing.
"""

from backend.agents.nodes.planner import planner_node
from backend.agents.nodes.executor import executor_node, identify_themes_node
from backend.agents.nodes.evaluator import evaluator_node
from backend.agents.nodes.strategist import strategist_node
from backend.agents.nodes.reporter import reporter_node
from backend.agents.nodes.search import search_node, merge_results_node

__all__ = [
    "planner_node",
    "executor_node",
    "identify_themes_node",
    "evaluator_node",
    "strategist_node",
    "reporter_node",
    "search_node",
    "merge_results_node",
]
