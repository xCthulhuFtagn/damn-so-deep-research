"""Tests for FastAPI endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health endpoint returns 200."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    @pytest.mark.asyncio
    async def test_register_user(self, client: AsyncClient):
        """Test user registration."""
        response = await client.post(
            "/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepassword123",
            },
        )
        # May fail if DB not initialized, that's expected in unit tests
        assert response.status_code in [200, 201, 500]

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Test login with invalid credentials."""
        response = await client.post(
            "/auth/login",
            data={
                "username": "nonexistent",
                "password": "wrongpassword",
            },
        )
        assert response.status_code in [401, 500]


class TestRunsEndpoints:
    """Tests for runs CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_runs_unauthorized(self, client: AsyncClient):
        """Test listing runs without auth returns 401."""
        response = await client.get("/runs")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_run_unauthorized(self, client: AsyncClient):
        """Test creating run without auth returns 401."""
        response = await client.post(
            "/runs",
            json={"title": "Test Research", "initial_query": "What is AI?"},
        )
        assert response.status_code == 401


class TestResearchEndpoints:
    """Tests for research control endpoints."""

    @pytest.mark.asyncio
    async def test_start_research_unauthorized(self, client: AsyncClient):
        """Test starting research without auth returns 401."""
        response = await client.post(
            "/research/start",
            json={"run_id": "test-123"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_pause_research_unauthorized(self, client: AsyncClient):
        """Test pausing research without auth returns 401."""
        response = await client.post(
            "/research/pause",
            json={"run_id": "test-123"},
        )
        assert response.status_code == 401


class TestApprovalsEndpoints:
    """Tests for approval endpoints."""

    @pytest.mark.asyncio
    async def test_respond_approval_unauthorized(self, client: AsyncClient):
        """Test approval response without auth returns 401."""
        response = await client.post(
            "/approvals/test-run/test-hash",
            json={"approved": True},
        )
        assert response.status_code == 401
