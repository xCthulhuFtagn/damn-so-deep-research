"""Pytest configuration and fixtures."""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.persistence.database import Database


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[Database, None]:
    """Create a test database."""
    db = Database(":memory:")
    await db.initialize()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_research_state() -> dict:
    """Sample research state for testing."""
    return {
        "messages": [],
        "plan": [],
        "current_step_index": 0,
        "phase": "planning",
        "active_agent": "planner",
        "search_themes": [],
        "parallel_search_results": [],
        "step_findings": [],
        "step_search_count": 0,
        "pending_approval": None,
        "pending_question": None,
        "run_id": "test-run-123",
        "user_id": "test-user-456",
        "total_tokens": 0,
        "error": None,
    }
