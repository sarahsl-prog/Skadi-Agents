"""Chaos tests for concurrent branch writes.

Two concurrent updates to the same branch must trigger optimistic
concurrency control: one writer wins, the other gets
:class:`VersionConflictError`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
import pytest

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.persistence import (
    CasePersistence,
    PersistencePool,
    VersionConflictError,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def pg_pool() -> AsyncGenerator[dict[str, Any]]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

        import subprocess
        import sys
        from pathlib import Path

        sync_dsn = dsn.replace("postgresql://", "postgresql+psycopg2://")
        env = {**os.environ, "DATABASE_URL": sync_dsn}
        for key in list(env.keys()):
            if key.startswith("WOLFPACK_"):
                env.pop(key, None)
        alembic_path = str((Path(sys.executable).parent / "alembic").resolve())
        subprocess.run(  # noqa: S603
            [alembic_path, "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        yield {"pool": pool, "dsn": dsn}
        await pool.close()


class TestConcurrentBranchWrites:
    """Optimistic concurrency under simultaneous writers."""

    @pytest.mark.asyncio
    async def test_concurrent_update_one_wins(self, pg_pool: dict[str, Any]) -> None:
        persistence = CasePersistence(PersistencePool(pg_pool["dsn"]))
        await persistence._pool.connect()

        case_id = str(uuid.uuid4())
        # Create parent case
        from wolfpack.schemas.case_state import CaseState
        from wolfpack.schemas.seed import Seed

        case = CaseState(
            case_id=case_id,
            seed=Seed(type="ioc", raw_payload={}),
        )
        await persistence.create_case(case)

        # Create branch
        branch_id = str(uuid.uuid4())
        branch = BranchState(
            branch_id=branch_id,
            case_id=case_id,
            spec=BranchSpec(
                hypothesis=Hypothesis(
                    description="test", confidence=Confidence.WEAK, status="open"
                ),
                created_by="test",
            ),
        )
        await persistence.create_branch(branch)

        async def _updater(expected_version: int) -> int | None:
            try:
                return await persistence.update_branch(branch_id, "closed", expected_version)
            except VersionConflictError:
                return None

        # Both try to update version 1 → only one succeeds
        results = await asyncio.gather(
            _updater(1),
            _updater(1),
        )
        assert any(r is not None for r in results)
        assert any(r is None for r in results)

    @pytest.mark.asyncio
    async def test_version_increments_on_success(self, pg_pool: dict[str, Any]) -> None:
        persistence = CasePersistence(PersistencePool(pg_pool["dsn"]))
        await persistence._pool.connect()

        case_id = str(uuid.uuid4())
        from wolfpack.schemas.case_state import CaseState
        from wolfpack.schemas.seed import Seed

        case = CaseState(
            case_id=case_id,
            seed=Seed(type="ioc", raw_payload={}),
        )
        await persistence.create_case(case)

        branch_id = str(uuid.uuid4())
        branch = BranchState(
            branch_id=branch_id,
            case_id=case_id,
            spec=BranchSpec(
                hypothesis=Hypothesis(
                    description="test", confidence=Confidence.WEAK, status="open"
                ),
                created_by="test",
            ),
        )
        await persistence.create_branch(branch)

        new_version = await persistence.update_branch(branch_id, "closed", 1)
        assert new_version == 2

        with pytest.raises(VersionConflictError):
            await persistence.update_branch(branch_id, "closed", 1)

        new_version_2 = await persistence.update_branch(branch_id, "abandoned", 2)
        assert new_version_2 == 3
