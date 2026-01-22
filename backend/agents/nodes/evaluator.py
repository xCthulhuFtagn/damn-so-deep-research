"""
Evaluator node - validates research findings.

Decides whether step findings are sufficient, need retry, or should be skipped.
"""

import logging
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.types import Command

from backend.agents.state import ResearchState
from backend.core.llm import get_llm

logger = logging.getLogger(__name__)

EVALUATOR_PROMPT = """You are a QA Evaluator for a research system.

Your job is to evaluate the research findings for the current task and decide the next action.

TASK DESCRIPTION:
{task_description}

COLLECTED FINDINGS:
{findings}

EVALUATION CRITERIA:
1. Are the findings relevant to the task?
2. Do they provide actionable or useful information?
3. Are there enough details to include in a research report?

YOUR DECISION OPTIONS:
1. APPROVE - Findings are sufficient. Provide a concise summary of the key insights.
2. FAIL - Findings are completely inadequate or missing. This is a critical failure.
3. SKIP - Findings are not great but the task is not critical. We can move on.

OUTPUT FORMAT:
First line: DECISION: [APPROVE/FAIL/SKIP]
Following lines: Your reasoning and, for APPROVE, a summary of key findings.

Example APPROVE output:
DECISION: APPROVE
Summary: The research found that X is Y. Key insights include A, B, and C.

Example FAIL output:
DECISION: FAIL
Reason: No relevant information was found despite search attempts.

Example SKIP output:
DECISION: SKIP
Reason: This is supplementary information. The main research can proceed without it."""


def parse_evaluation(content: str) -> tuple[str, str]:
    """Parse decision and reasoning from evaluator response."""
    lines = content.strip().split("\n")
    decision = "APPROVE"  # Default
    reasoning = ""

    for i, line in enumerate(lines):
        line = line.strip()
        if line.upper().startswith("DECISION:"):
            decision_text = line[9:].strip().upper()
            if "FAIL" in decision_text:
                decision = "FAIL"
            elif "SKIP" in decision_text:
                decision = "SKIP"
            else:
                decision = "APPROVE"
            # Rest is reasoning
            reasoning = "\n".join(lines[i + 1 :]).strip()
            break

    # If no decision found, use whole content as reasoning
    if not reasoning:
        reasoning = content

    return decision, reasoning


async def evaluator_node(
    state: ResearchState,
) -> Command[Literal["identify_themes", "strategist", "reporter"]]:
    """
    Evaluates findings for the current step.

    Routes to:
    - identify_themes: If approved, move to next step
    - strategist: If failed and critical, attempt recovery
    - reporter: If all steps done
    """
    run_id = state["run_id"]
    plan = state["plan"]
    current_idx = state["current_step_index"]
    findings = state.get("step_findings", [])

    logger.info(f"Evaluator for run {run_id}, step {current_idx}")

    current_step = plan[current_idx] if current_idx < len(plan) else None
    if not current_step:
        logger.warning("No current step found")
        return Command(
            update={"phase": "reporting"},
            goto="reporter",
        )

    # Build findings text
    findings_text = "\n\n".join(findings) if findings else "No findings collected."

    # Evaluate
    llm = get_llm(temperature=0.0)
    messages = [
        SystemMessage(
            content=EVALUATOR_PROMPT.format(
                task_description=current_step["description"],
                findings=findings_text,
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    decision, reasoning = parse_evaluation(response.content)

    logger.info(f"Evaluator decision: {decision}")

    # Update plan based on decision
    updated_plan = plan.copy()

    if decision == "APPROVE":
        # Mark step as done with result
        updated_plan[current_idx] = {
            **current_step,
            "status": "DONE",
            "result": reasoning,
        }

        # Check if more steps
        remaining = [s for s in updated_plan if s["status"] == "TODO"]
        if remaining:
            return Command(
                update={
                    "plan": updated_plan,
                    "current_step_index": current_idx + 1,
                    "phase": "identifying_themes",
                    "step_findings": [],
                },
                goto="identify_themes",
            )
        else:
            return Command(
                update={
                    "plan": updated_plan,
                    "phase": "reporting",
                },
                goto="reporter",
            )

    elif decision == "FAIL":
        # Mark as failed, route to strategist
        updated_plan[current_idx] = {
            **current_step,
            "status": "FAILED",
            "error": reasoning,
        }
        return Command(
            update={
                "plan": updated_plan,
                "failed_step_id": current_idx,
                "last_error": reasoning,
                "phase": "recovering",
            },
            goto="strategist",
        )

    else:  # SKIP
        # Mark as skipped, move on
        updated_plan[current_idx] = {
            **current_step,
            "status": "SKIPPED",
            "result": f"Skipped: {reasoning}",
        }

        remaining = [s for s in updated_plan if s["status"] == "TODO"]
        if remaining:
            return Command(
                update={
                    "plan": updated_plan,
                    "current_step_index": current_idx + 1,
                    "phase": "identifying_themes",
                    "step_findings": [],
                },
                goto="identify_themes",
            )
        else:
            return Command(
                update={
                    "plan": updated_plan,
                    "phase": "reporting",
                },
                goto="reporter",
            )
