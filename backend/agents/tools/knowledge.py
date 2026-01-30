"""
Knowledge-based answering tool.

Allows agents to provide answers from their built-in knowledge
without requiring external search.
"""

import logging

logger = logging.getLogger(__name__)


async def answer_from_knowledge(answer: str) -> str:
    """
    Provide an answer from the agent's knowledge.

    This tool is used when the agent can answer a question
    without needing to search, or to confirm completion of a task.

    Args:
        answer: The answer or completion message

    Returns:
        The answer (echoed back for state tracking)
    """
    logger.info(f"Knowledge answer provided: {answer[:100]}...")
    return f"Knowledge-based answer: {answer}"


async def ask_user(question: str) -> str:
    """
    Ask the user a question.

    In the LangGraph system, this triggers an interrupt.
    The actual question/response flow is handled by the graph.

    Args:
        question: Question to ask the user

    Returns:
        Placeholder - actual response comes via graph interrupt
    """
    logger.info(f"User question: {question}")
    # In LangGraph, this would trigger an interrupt
    # The response is handled by the graph execution flow
    return f"[Awaiting user response to: {question}]"
