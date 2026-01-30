"""
Search merger node - merges parallel search results into step findings.

Called after all parallel search workers complete (fan-in).
"""

import logging

from backend.agents.state import ResearchState

logger = logging.getLogger(__name__)


async def search_merger_node(state: ResearchState) -> dict:
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

    # Note: Do NOT clear parallel_search_results here!
    # The accumulator node needs to process them into executor_tool_history.
    # Accumulator will clear them after processing.
    return {
        "step_findings": merged_findings,
        # search_themes cleared here since dispatcher already used them
        "search_themes": [],
    }
