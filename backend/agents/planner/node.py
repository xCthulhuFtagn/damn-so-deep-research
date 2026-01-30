"""
Planner node - creates the research plan.

Takes user query and generates actionable research steps.
"""

import logging
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from backend.agents.state import ResearchState, create_plan_step
from backend.core.config import config
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)


def get_planner_prompt() -> str:
    """Generate planner prompt with config values."""
    min_steps = config.research.min_plan_steps
    max_steps = config.research.max_plan_steps

    return f"""You are the Lead Planner for a deep research system.

Your ONLY job is to create a research plan based on the user's query.

CRITICAL RULES:
1. Create {min_steps}-{max_steps} clear, actionable research steps.
2. Each step must be SELF-CONTAINED - it should not depend on information from other steps.
3. Steps should be specific research tasks that can be accomplished via web search.
4. FORBIDDEN: Do NOT include steps for "generating report", "summarizing findings", or "compiling results".
   - The final report is generated automatically by the Reporter agent.
   - Your plan must ONLY contain research and investigation steps.

OUTPUT FORMAT:
Output a numbered list of research steps, one per line:
1. [First research task]
2. [Second research task]
...

Be specific and actionable. Each step should answer a distinct aspect of the user's query."""


def parse_plan_steps(content: str) -> list[str]:
    """
    Parse numbered steps from LLM response.

    Handles formats like:
    - "1. Step one"
    - "1) Step one"
    - "- Step one"
    """
    lines = content.strip().split("\n")
    steps = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match numbered formats: "1. ", "1) ", "1: "
        match = re.match(r"^\d+[\.\)\:]\s*(.+)$", line)
        if match:
            steps.append(match.group(1).strip())
            continue

        # Match bullet formats: "- ", "* "
        match = re.match(r"^[\-\*]\s*(.+)$", line)
        if match:
            steps.append(match.group(1).strip())

    return steps


async def planner_node(
    state: ResearchState,
) -> dict:
    """
    Planner node - generates research plan from user query.

    Outputs:
        - Updates state.plan with PlanStep objects
        - Sets phase to "awaiting_confirmation"
        - Routes to executor subgraph (after user confirms)
    """
    logger.info(f"Planner node starting for run {state['run_id']}")

    llm = get_llm(temperature=0.0, run_id=state["run_id"])

    # Check if there's user feedback from a previous rejection
    user_feedback = state.get("user_response")
    previous_plan = state.get("plan", [])

    # Build messages
    planner_prompt = get_planner_prompt()

    if user_feedback and previous_plan:
        # Re-planning based on user feedback
        logger.info(f"Re-planning with user feedback: {user_feedback[:100]}...")
        previous_plan_text = "\n".join(
            f"{i+1}. {step['description']}" for i, step in enumerate(previous_plan)
        )
        messages = [
            SystemMessage(content=planner_prompt),
            HumanMessage(content=f"""Original query: {state["original_query"]}

Previous plan that was rejected:
{previous_plan_text}

User feedback for improvement:
{user_feedback}

Please create an improved research plan that addresses the user's feedback."""),
        ]
    else:
        # Initial planning
        messages = [
            SystemMessage(content=planner_prompt),
            HumanMessage(content=state["original_query"]),
        ]

    # Invoke LLM
    response = await llm.ainvoke(messages)
    logger.debug(f"Planner response: {response.content[:200]}...")

    # Parse steps from response
    step_descriptions = parse_plan_steps(response.content)

    if not step_descriptions:
        logger.warning("No steps parsed from planner response, using fallback")
        step_descriptions = [f"Research: {state['original_query']}"]

    # Create PlanStep objects with substep support
    plan = [
        create_plan_step(id=i, description=desc)
        for i, desc in enumerate(step_descriptions)
    ]

    logger.info(f"Created plan with {len(plan)} steps")

    return {
        "plan": plan,
        "phase": "awaiting_confirmation",
        "current_step_index": 0,
        "user_response": None,  # Clear user feedback after using it
        "needs_replan": False,  # Clear replan flag
        "messages": [
            HumanMessage(content=state["original_query"]),
            response,
        ],
    }
