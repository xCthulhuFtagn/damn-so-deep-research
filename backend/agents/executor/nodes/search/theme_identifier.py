"""
Theme identifier node - generates search themes for web_search tool.

Called AFTER decision node chooses web_search.
Generates search queries based on the task description or uses themes from decision params.
"""

import logging

from langchain_core.messages import SystemMessage

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

THEME_IDENTIFICATION_PROMPT = """You are a research assistant identifying search themes.

Given a research task, identify 1-3 specific search queries that would help complete this task.
Each query should target a different aspect or source of information.

OUTPUT FORMAT:
Output each search query on a separate line, prefixed with "SEARCH:":
SEARCH: [first search query]
SEARCH: [second search query]
SEARCH: [third search query]

Be specific and targeted. Good queries are:
- Focused on a single concept
- Include relevant keywords
- Avoid overly broad terms

IMPORTANT: Output ONLY the search queries in the format above. No other text."""


def parse_search_themes(content: str) -> list[str]:
    """Parse search queries from LLM response."""
    themes = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("SEARCH:"):
            query = line[7:].strip()
            if query:
                themes.append(query)
    return themes


async def theme_identifier_node(state: ResearchState) -> dict:
    """
    Generate search themes for web_search tool.

    Called after decision node chooses web_search. Handles:
    - Using themes from decision params if provided
    - Generating new themes via LLM from task description
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]
    decision = state.get("executor_decision", {})
    params = decision.get("params", {})

    logger.info(f"Theme identifier for run {run_id}, step {current_idx}")

    # If decision already has themes, use them
    if params.get("themes"):
        themes = params["themes"]
        logger.info(f"Using {len(themes)} themes from decision params: {themes}")
        return {"search_themes": themes}

    # Get current task description
    task_description = ""
    if current_idx < len(plan):
        task_description = plan[current_idx].get("description", "")

    if not task_description:
        logger.warning("No task description found, using original query")
        task_description = state.get("original_query", "research topic")

    # Generate themes via LLM
    llm = get_llm(temperature=0.0)

    messages = [
        SystemMessage(content=THEME_IDENTIFICATION_PROMPT),
        SystemMessage(content=f"Research task: {task_description}"),
    ]

    response = await llm.ainvoke(messages)
    themes = parse_search_themes(response.content)

    if not themes:
        # Fallback: use the task description as a single query
        themes = [task_description]

    # Limit to max 3 themes
    themes = themes[:3]

    logger.info(f"Generated {len(themes)} search themes: {themes}")

    return {"search_themes": themes}
