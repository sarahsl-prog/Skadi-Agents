"""Unit tests for persistence helpers (mocked asyncpg)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.persistence import (
    CasePersistence,
    PersistencePool,
    VersionConflictError,
)
from wolfpack.schemas.seed import Seed


@pytest.fixture()
def mock_pool() -> Any:
    pool = MagicMock(spec=PersistencePool)
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    return pool


@pytest.fixture()
def persistence(mock_pool: Any) -> CasePersistence:
    return CasePersistence(mock_pool)


class TestPersistencePool:
    async def test_connect_creates_pool(self) -> None:
        pool = PersistencePool("postgresql://localhost/test")
        assert pool._pool is None


class TestCasePersistence:
    async def test_create_case(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn

        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
        )
        await persistence.create_case(case)

        mock_conn.execute.assert_awaited_once()
        mock_pool.release.assert_called_once_with(mock_conn)

    async def test_get_case_found(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        case_id = str(uuid.uuid4())
        mock_conn.fetchrow.return_value = {
            "id": uuid.UUID(case_id),
            "seed": {"type": "ioc", "raw_payload": {"value": "10.0.0.1"}, "metadata": {}},
            "status": "new",
            "version": 1,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

        result = await persistence.get_case(case_id)
        assert result is not None
        assert result.case_id == case_id
        assert result.status == "new"

    async def test_get_case_not_found(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        result = await persistence.get_case(str(uuid.uuid4()))
        assert result is None

    async def test_update_case_success(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetchrow.return_value = {"version": 2}

        new_version = await persistence.update_case("case-1", "scented", expected_version=1)
        assert new_version == 2

    async def test_update_case_conflict(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        with pytest.raises(VersionConflictError):
            await persistence.update_case("case-1", "scented", expected_version=1)

    async def test_create_branch(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn

        branch = BranchState(
            branch_id=str(uuid.uuid4()),
            case_id=str(uuid.uuid4()),
            spec=BranchSpec(
                hypothesis=Hypothesis(description="h", confidence=Confidence.WEAK),
                created_by="alpha",
            ),
        )
        await persistence.create_branch(branch)

        mock_conn.execute.assert_awaited_once()

    async def test_update_branch_success(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetchrow.return_value = {"version": 3}

        new_version = await persistence.update_branch("branch-1", "closed", expected_version=2)
        assert new_version == 3

    async def test_create_hypothesis(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn

        hyp = Hypothesis(description="test", confidence=Confidence.PLAUSIBLE)
        hypothesis_id = await persistence.create_hypothesis(hyp, "branch-1")

        assert hypothesis_id
        mock_conn.execute.assert_awaited_once()

    async def test_list_hypotheses(
        self, persistence: CasePersistence, mock_pool: Any
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetch.return_value = [
            {"description": "h1", "confidence": 3, "status": "open"},
            {"description": "h2", "confidence": 4, "status": "confirmed"},
        ]

        results = await persistence.list_hypotheses_for_branch("branch-1")
        assert len(results) == 2
        assert results[0].confidence == Confidence.PLAUSIBLE
        assert results[1].confidence == Confidence.STRONG
