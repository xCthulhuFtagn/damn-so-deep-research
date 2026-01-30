"""
Search worker node - executes a single search query.

Uses LangGraph's Send API for parallel search fan-out.
Each worker instance handles one search query.
"""

import logging
from typing import Any

from backend.agents.state import SearchResult

logger = logging.getLogger(__name__)


async def search_worker_node(state: dict[str, Any]) -> dict:
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
    logger.info(f"Search worker executing query: {query}")

    # Import here to avoid circular imports
    from backend.agents.tools.search import intelligent_web_search

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

        logger.info(f"Search worker completed for '{query}': {len(findings)} findings")

        return {
            "parallel_search_results": [search_result],
            "step_search_count": 1,
        }

    except Exception as e:
        logger.error(f"Search worker failed for '{query}': {e}")
        # Return empty result on error
        return {
            "parallel_search_results": [
                SearchResult(query=query, findings=[f"Search error: {str(e)}"], sources=[])
            ],
            "step_search_count": 1,
        }
