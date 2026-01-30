"""
Accumulator node - collects results from tool executions.

Handles merging web search results from parallel_search_results into tool history.
"""

import logging

from backend.agents.state import ExecutorToolCall, ResearchState

logger = logging.getLogger(__name__)


async def accumulator_node(state: ResearchState) -> dict:
    """
    Accumulate tool results, handling web search merge specially.

    For web_search: Merges parallel_search_results into a single tool call record.
    For other tools: Results are already in executor_tool_history.
    """
    run_id = state.get("run_id", "")
    decision = state.get("executor_decision", {})
    tool_history = state.get("executor_tool_history", [])
    parallel_results = state.get("parallel_search_results", [])

    last_tool = decision.get("decision", "") if decision else ""

    logger.info(f"Accumulator for run {run_id}, last tool: {last_tool}")

    updates = {}

    # Handle web search results
    if last_tool == "web_search" and parallel_results:
        # Merge parallel search results into a single tool call
        merged_findings = []
        merged_sources = []
        search_queries = []

        for result in parallel_results:
            search_queries.append(result.get("query", ""))
            merged_findings.extend(result.get("findings", []))
            merged_sources.extend(result.get("sources", []))

        # Deduplicate sources
        unique_sources = list(dict.fromkeys(merged_sources))

        # Create merged result string
        result_text = "\n\n---\n\n".join(merged_findings) if merged_findings else "(no results)"
        if unique_sources:
            result_text += f"\n\nSources: {', '.join(unique_sources[:10])}"

        # Create tool call record for the web search
        tool_call = ExecutorToolCall(
            id=len(tool_history) + 1,
            tool="web_search",
            params={"themes": search_queries},
            result=result_text,
            success=len(merged_findings) > 0,
            error=None if merged_findings else "No results found",
        )

        updates["executor_tool_history"] = tool_call  # Append via reducer
        updates["executor_call_count"] = 1  # Web search fanout counts as 1 call
        updates["parallel_search_results"] = None  # Clear parallel results
        updates["search_themes"] = []  # Clear themes

        logger.info(f"Merged {len(parallel_results)} search results into tool history")

    # Update phase back to executing
    updates["phase"] = "executing"

    return updates
