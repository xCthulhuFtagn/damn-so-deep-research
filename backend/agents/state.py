"""
LangGraph state schema for the research system.

Defines the ResearchState TypedDict that flows through the graph.
"""

from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages


class PlanStep(TypedDict):
    """A single step in the research plan."""

    id: int
    description: str
    status: Literal["TODO", "IN_PROGRESS", "DONE", "FAILED", "SKIPPED"]
    result: Optional[str]
    error: Optional[str]


class SearchResult(TypedDict):
    """Result from a parallel search operation."""

    query: str
    findings: list[str]
    sources: list[str]


def merge_search_results(
    existing: list[SearchResult], new: list[SearchResult]
) -> list[SearchResult]:
    """Reducer for merging parallel search results."""
    return existing + new


def merge_findings(existing: list[str], new: list[str]) -> list[str]:
    """Reducer for merging step findings."""
    return existing + new


def add_or_reset_count(existing: int, new: int) -> int:
    """
    Reducer for count updates that can be reset or incremented.

    - If new == 0, resets the count to 0 (used before parallel operations)
    - If new > 0, adds to existing count (used by parallel nodes)
    - Negative values are treated as absolute reset to |new|
    """
    if new == 0:
        return 0  # Reset
    elif new < 0:
        return abs(new)  # Absolute set
    else:
        return existing + new  # Increment


class ResearchState(TypedDict):
    """
    Main state schema for the research graph.

    This state flows through all nodes and is persisted by the checkpointer.
    """

    # --- Core Conversation ---
    # Messages are appended using add_messages reducer
    messages: Annotated[list, add_messages]

    # --- Research Plan ---
    plan: list[PlanStep]
    current_step_index: int

    # --- Execution Phase Tracking ---
    phase: Literal[
        "planning",
        "awaiting_confirmation",
        "identifying_themes",
        "searching",
        "evaluating",
        "recovering",
        "reporting",
        "done",
        "paused",
    ]

    # --- Parallel Search Context ---
    search_themes: list[str]  # Themes to search in parallel
    parallel_search_results: Annotated[list[SearchResult], merge_search_results]
    step_findings: Annotated[list[str], merge_findings]  # Collected findings for current step

    # --- Step Execution Tracking ---
    step_search_count: Annotated[int, add_or_reset_count]  # Searches performed in current step
    max_searches_per_step: int  # Limit (default 3)

    # --- Human-in-the-Loop ---
    pending_approval: Optional[dict]  # {command: str, hash: str}
    pending_question: Optional[str]
    user_response: Optional[str]

    # --- Error Recovery ---
    last_error: Optional[str]
    failed_step_id: Optional[int]
    recovery_attempts: int

    # --- Metadata ---
    run_id: str
    user_id: str
    original_query: str
    total_tokens: int


def create_initial_state(
    run_id: str,
    user_id: str,
    query: str,
) -> ResearchState:
    """
    Create initial state for a new research run.

    Args:
        run_id: Unique run identifier
        user_id: User identifier
        query: Initial research query

    Returns:
        Initial ResearchState
    """
    return ResearchState(
        messages=[],
        plan=[],
        current_step_index=0,
        phase="planning",
        search_themes=[],
        parallel_search_results=[],
        step_findings=[],
        step_search_count=0,
        max_searches_per_step=3,
        pending_approval=None,
        pending_question=None,
        user_response=None,
        last_error=None,
        failed_step_id=None,
        recovery_attempts=0,
        run_id=run_id,
        user_id=user_id,
        original_query=query,
        total_tokens=0,
    )
