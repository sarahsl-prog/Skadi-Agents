"""Integration tests for the Analyst Console API.

Uses FastAPI TestClient so no running server or database is required.
All DB calls are mocked at the persistence layer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from wolfpack.api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _mock_pool():
    """Patch the global persistence pool used by API routes."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    async def _acquire():
        return mock_conn

    async def _release(conn: Any) -> None:
        pass

    mock_pool.acquire = _acquire
    mock_pool.release = _release

    with (
        patch("wolfpack.api.routes.cases._pool", mock_pool),
        patch("wolfpack.api.routes.review._pool", mock_pool),
        patch("wolfpack.api.routes.breakglass._pool", mock_pool),
    ):
        yield mock_pool, mock_conn


@pytest.fixture
def api_token() -> str:
    from wolfpack.api.auth import _DEFAULT_TOKEN

    return _DEFAULT_TOKEN


class TestHealth:
    def test_health_endpoint(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCases:
    def test_list_cases_unauthorized(self, client: TestClient) -> None:
        resp = client.get("/api/cases")
        assert resp.status_code == 403

    def test_list_cases_empty(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.fetch = AsyncMock(return_value=[])

        resp = client.get("/api/cases", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cases"] == []

    def test_get_case_not_found(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.fetchrow = AsyncMock(return_value=None)

        resp = client.get("/api/cases/nonexistent", headers={"X-API-Token": api_token})
        assert resp.status_code == 404

    def test_get_case_timeline(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.fetch = AsyncMock(return_value=[])

        resp = client.get("/api/cases/abc/timeline", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == "abc"
        assert data["events"] == []

    def test_get_case_verdict_missing(
        self, client: TestClient, api_token: str, _mock_pool: Any
    ) -> None:
        _, mock_conn = _mock_pool
        mock_conn.fetchrow = AsyncMock(return_value=None)

        resp = client.get("/api/cases/abc/verdict", headers={"X-API-Token": api_token})
        assert resp.status_code == 404


class TestReview:
    def test_review_queue_unauthorized(self, client: TestClient) -> None:
        resp = client.get("/api/review/queue")
        assert resp.status_code == 403

    def test_approve_case(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = client.post("/api/review/abc/approve", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == "abc"
        assert data["status"] == "approved"

    def test_escalate_case(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = client.post("/api/review/abc/escalate", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "escalation"

    def test_close_benign(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = client.post("/api/review/abc/close_benign", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "closed"

    def test_continue_hunt(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        resp = client.post("/api/review/abc/continue_hunt", headers={"X-API-Token": api_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scented"


class TestBreakGlass:
    def test_show_raw_unauthorized(self, client: TestClient) -> None:
        resp = client.post("/api/cases/abc/show-raw", params={"field": "token_1"})
        assert resp.status_code == 403

    def test_show_raw_not_found(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        _, mock_conn = _mock_pool
        with patch("wolfpack.api.routes.breakglass.show_raw", new=AsyncMock(return_value=None)):
            resp = client.post(
                "/api/cases/abc/show-raw",
                params={"field": "token_1"},
                headers={"X-API-Token": api_token},
            )
        assert resp.status_code == 404

    def test_show_raw_success(self, client: TestClient, api_token: str, _mock_pool: Any) -> None:
        with patch("wolfpack.api.routes.breakglass.show_raw", new=AsyncMock(return_value="secret")):
            resp = client.post(
                "/api/cases/abc/show-raw",
                params={"field": "token_1"},
                headers={"X-API-Token": api_token},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["raw"] == "secret"
