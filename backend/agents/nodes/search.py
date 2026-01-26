"""
Search nodes - parallel search execution and result merging.

Uses LangGraph's Send API for parallel search fan-out.
"""

import logging
from typing import Any

from backend.agents.state import ResearchState, SearchResult

logger = logging.getLogger(__name__)


async def search_node(state: dict[str, Any]) -> dict:
    """
    Execute a single search query.

    This node is invoked in parallel via the Send API.
    Each invocation receives a subset of state with the query to execute.

    Args:
        state: Must contain 'query' key with the search query

    Returns:
        Dict with search results to merge into parent state
    """
    query = state.get("query", "")
    logger.info(f"Search node executing query: {query}")

    # Import here to avoid circular imports
    from backend.tools.search import intelligent_web_search

    try:
        # Execute search
        result = await intelligent_web_search(query)

        # Parse findings from result
        findings = []
        sources = []

        if result and "No relevant information" not in result:
            # Extract content - the search tool returns formatted markdown
            findings.append(result)

            # Extract URLs from result (rough parsing)
            import re
            urls = re.findall(r'https?://[^\s\)]+', result)
            sources.extend(urls[:5])  # Limit sources

        search_result = SearchResult(
            query=query,
            findings=findings,
            sources=sources,
        )

        logger.info(f"Search completed for '{query}': {len(findings)} findings")

        return {
            "parallel_search_results": [search_result],
            "step_search_count": 1,
        }

    except Exception as e:
        logger.error(f"Search failed for '{query}': {e}")
        # Return empty result on error
        return {
            "parallel_search_results": [
                SearchResult(query=query, findings=[f"Search error: {str(e)}"], sources=[])
            ],
            "step_search_count": 1,
        }


async def merge_results_node(state: ResearchState) -> dict:
    """
    Merge parallel search results into step findings.

    Called after all parallel searches complete (fan-in).
    """
    logger.info(f"Merging search results for run {state['run_id']}")

    parallel_results = state.get("parallel_search_results", [])

    # Combine all findings
    merged_findings = []
    all_sources = []

    for result in parallel_results:
        merged_findings.extend(result.get("findings", []))
        all_sources.extend(result.get("sources", []))

    # Deduplicate sources
    unique_sources = list(dict.fromkeys(all_sources))

    logger.info(
        f"Merged {len(merged_findings)} findings from {len(parallel_results)} searches"
    )

    return {
        "step_findings": merged_findings,
        "parallel_search_results": None,  # Reset signal - clears accumulated results
        "search_themes": [],  # Clear themes
        "phase": "evaluating",
    }
