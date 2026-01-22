"""Tests for research state and reducers."""

import pytest

from backend.agents.state import (
    ResearchState,
    PlanStep,
    SearchResult,
    merge_search_results,
    merge_findings,
)


class TestPlanStep:
    """Tests for PlanStep TypedDict."""

    def test_create_plan_step(self):
        """Test creating a plan step."""
        step: PlanStep = {
            "id": 1,
            "description": "Research AI safety",
            "status": "TODO",
            "result": None,
            "error": None,
        }
        assert step["id"] == 1
        assert step["status"] == "TODO"

    def test_plan_step_statuses(self):
        """Test all valid plan step statuses."""
        valid_statuses = ["TODO", "IN_PROGRESS", "DONE", "FAILED", "SKIPPED"]
        for status in valid_statuses:
            step: PlanStep = {
                "id": 1,
                "description": "Test step",
                "status": status,
                "result": None,
                "error": None,
            }
            assert step["status"] == status


class TestSearchResult:
    """Tests for SearchResult TypedDict."""

    def test_create_search_result(self):
        """Test creating a search result."""
        result: SearchResult = {
            "theme": "AI safety",
            "query": "AI safety regulations",
            "results": [{"title": "Test", "url": "https://example.com", "content": "..."}],
            "findings": ["Finding 1", "Finding 2"],
        }
        assert result["theme"] == "AI safety"
        assert len(result["findings"]) == 2


class TestMergeSearchResults:
    """Tests for merge_search_results reducer."""

    def test_merge_empty_lists(self):
        """Test merging empty lists."""
        result = merge_search_results([], [])
        assert result == []

    def test_merge_with_existing(self):
        """Test merging new results with existing."""
        existing: list[SearchResult] = [
            {
                "theme": "Theme 1",
                "query": "Query 1",
                "results": [],
                "findings": ["Finding 1"],
            }
        ]
        new: list[SearchResult] = [
            {
                "theme": "Theme 2",
                "query": "Query 2",
                "results": [],
                "findings": ["Finding 2"],
            }
        ]
        result = merge_search_results(existing, new)
        assert len(result) == 2
        assert result[0]["theme"] == "Theme 1"
        assert result[1]["theme"] == "Theme 2"


class TestMergeFindings:
    """Tests for merge_findings reducer."""

    def test_merge_findings(self):
        """Test merging findings lists."""
        existing = ["Finding 1"]
        new = ["Finding 2", "Finding 3"]
        result = merge_findings(existing, new)
        assert len(result) == 3
        assert "Finding 1" in result
        assert "Finding 2" in result

    def test_merge_empty(self):
        """Test merging with empty lists."""
        result = merge_findings([], ["New finding"])
        assert result == ["New finding"]


class TestResearchState:
    """Tests for ResearchState initialization."""

    def test_initial_state(self, sample_research_state):
        """Test initial state values."""
        state: ResearchState = sample_research_state
        assert state["phase"] == "planning"
        assert state["current_step_index"] == 0
        assert len(state["messages"]) == 0
        assert len(state["plan"]) == 0

    def test_state_phases(self):
        """Test all valid phases."""
        valid_phases = [
            "planning",
            "identifying_themes",
            "searching",
            "evaluating",
            "recovering",
            "reporting",
            "done",
            "paused",
        ]
        for phase in valid_phases:
            state: ResearchState = {
                "messages": [],
                "plan": [],
                "current_step_index": 0,
                "phase": phase,
                "active_agent": "test",
                "search_themes": [],
                "parallel_search_results": [],
                "step_findings": [],
                "step_search_count": 0,
                "pending_approval": None,
                "pending_question": None,
                "run_id": "test",
                "user_id": "test",
                "total_tokens": 0,
                "error": None,
            }
            assert state["phase"] == phase
