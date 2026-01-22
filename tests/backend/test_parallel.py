"""Tests for parallel search functionality."""

import pytest
from langgraph.constants import Send

from backend.agents.parallel.search_fanout import fanout_searches
from backend.agents.state import ResearchState


class TestFanoutSearches:
    """Tests for the parallel search fan-out function."""

    def test_fanout_single_theme(self, sample_research_state):
        """Test fan-out with a single search theme."""
        state = sample_research_state.copy()
        state["search_themes"] = ["AI safety regulations"]

        sends = fanout_searches(state)

        assert len(sends) == 1
        assert isinstance(sends[0], Send)
        assert sends[0].node == "search_node"
        assert sends[0].arg["theme"] == "AI safety regulations"

    def test_fanout_multiple_themes(self, sample_research_state):
        """Test fan-out with multiple search themes."""
        state = sample_research_state.copy()
        state["search_themes"] = [
            "AI safety regulations",
            "EU AI Act 2024",
            "NIST AI framework",
        ]

        sends = fanout_searches(state)

        assert len(sends) == 3
        themes = [s.arg["theme"] for s in sends]
        assert "AI safety regulations" in themes
        assert "EU AI Act 2024" in themes
        assert "NIST AI framework" in themes

    def test_fanout_empty_themes(self, sample_research_state):
        """Test fan-out with no themes returns empty list."""
        state = sample_research_state.copy()
        state["search_themes"] = []

        sends = fanout_searches(state)

        assert len(sends) == 0

    def test_fanout_preserves_context(self, sample_research_state):
        """Test fan-out preserves run_id and step_index."""
        state = sample_research_state.copy()
        state["search_themes"] = ["Test theme"]
        state["run_id"] = "run-abc-123"
        state["current_step_index"] = 5

        sends = fanout_searches(state)

        assert sends[0].arg["run_id"] == "run-abc-123"
        assert sends[0].arg["step_index"] == 5

    def test_fanout_max_themes(self, sample_research_state):
        """Test fan-out handles many themes."""
        state = sample_research_state.copy()
        state["search_themes"] = [f"Theme {i}" for i in range(10)]

        sends = fanout_searches(state)

        # Should create a Send for each theme
        assert len(sends) == 10
