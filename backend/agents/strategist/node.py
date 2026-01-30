"""
Strategist node - recovery from failed substeps.

Generates alternative search queries based on previous failed attempts.
Does NOT create new plan steps - works within the current step's substep budget.
"""

import logging
import re
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.types import Command

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

STRATEGIST_PROMPT = """You are a Recovery Strategist for a research system.

A research SUBSTEP has failed. Your job is to suggest ALTERNATIVE SEARCH QUERIES.

ORIGINAL RESEARCH QUERY:
{original_query}

CURRENT STEP:
{step_description}

SUBSTEP ATTEMPT #{substep_number} FAILED:
{error}

PREVIOUS ATTEMPTS:
{previous_attempts}

PARTIAL FINDINGS COLLECTED:
{partial_findings}

YOUR TASK:
Generate 1-3 ALTERNATIVE search queries that approach the problem differently.

STRATEGIES TO TRY:
1. More specific terminology or jargon
2. Different phrasing / synonyms
3. Narrower scope (if previous was too broad)
4. Broader scope (if previous was too narrow)
5. Alternative sources (academic papers, news, official documents)
6. Related topics that might contain the answer

OUTPUT FORMAT:
SEARCH: [alternative query 1]
SEARCH: [alternative query 2]
SEARCH: [alternative query 3]

RULES:
- Do NOT repeat previous failed queries
- Each query should try a distinctly different approach
- Be specific and actionable"""


def parse_search_queries(content: str) -> list[str]:
    """Parse search queries from strategist response."""
    queries = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Match "SEARCH: query" format
        if line.upper().startswith("SEARCH:"):
            query = line[7:].strip()
            if query:
                queries.append(query)
            continue

        # Match numbered format: "1. query"
        match = re.match(r"^\d+[\.\)]\s*(.+)$", line)
        if match:
            queries.append(match.group(1).strip())
            continue

        # Match bullet format: "- query"
        match = re.match(r"^[\-\*]\s*(.+)$", line)
        if match:
            queries.append(match.group(1).strip())

    return queries


async def strategist_node(
    state: ResearchState,
) -> Command[Literal["executor", "reporter"]]:
    """
    Recovery strategist - generates alternative search queries.

    Does NOT create new plan steps. Instead:
    - Analyzes previous failed substeps
    - Generates new search themes for retry
    - Routes back to executor with context for the SAME step
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]
    error = state.get("last_error", "Unknown error")

    logger.info(f"Strategist for run {run_id}, step {current_idx}")

    if current_idx >= len(plan):
        logger.warning("Invalid step index, moving to reporter")
        return Command(
            update={"phase": "reporting"},
            goto="reporter",
        )

    current_step = plan[current_idx]
    substeps = current_step.get("substeps", [])
    substep_idx = current_step.get("current_substep_index", 0)
    accumulated = current_step.get("accumulated_findings", [])

    # Build context from previous attempts
    if substeps:
        prev_attempts = []
        for s in substeps:
            queries_str = ", ".join(s.get("search_queries", []))
            prev_attempts.append(
                f"  Attempt {s['id'] + 1}: queries=[{queries_str}], error={s.get('error', 'N/A')[:100]}"
            )
        previous_attempts_text = "\n".join(prev_attempts)
    else:
        previous_attempts_text = "None (first attempt)"

    partial_text = (
        "\n".join(accumulated[:5]) if accumulated else "No partial findings yet"
    )

    # Generate alternative queries
    llm = get_llm(temperature=0.5)  # Higher creativity for alternatives
    messages = [
        SystemMessage(
            content=STRATEGIST_PROMPT.format(
                original_query=state["original_query"],
                step_description=current_step["description"],
                substep_number=substep_idx,
                error=error,
                previous_attempts=previous_attempts_text,
                partial_findings=partial_text,
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    alternative_queries = parse_search_queries(response.content)

    if not alternative_queries:
        # Fallback: reformulate the original step description
        alternative_queries = [
            f"{current_step['description']} overview",
            f"{current_step['description']} examples",
        ]

    # Limit to 3 queries
    alternative_queries = alternative_queries[:3]

    logger.info(f"Generated {len(alternative_queries)} alternative queries for retry")

    # Route back to executor with new search themes
    # executor will use these directly since step is IN_PROGRESS
    return Command(
        update={
            "search_themes": alternative_queries,
            "phase": "searching",
            "step_findings": [],  # Clear for new attempt
            "last_error": None,
        },
        goto="executor",
    )
