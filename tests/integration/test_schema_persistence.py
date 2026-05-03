"""Integration tests for schema persistence against real Postgres."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.persistence import CasePersistence, PersistencePool, VersionConflictError
from wolfpack.schemas.seed import Seed

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled (SKIP_INTEGRATION=1)",
)


@pytest.fixture()
async def persistence_pool() -> AsyncGenerator[PersistencePool]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16").start() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = PersistencePool(dsn, min_size=1, max_size=2)
        await pool.connect()

        # Apply migrations
        import subprocess
        import sys

        sync_dsn = dsn.replace("postgresql://", "postgresql+psycopg2://")
        env = {**os.environ, "DATABASE_URL": sync_dsn}
        # Remove env vars that would cause Settings() to fail if read
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

        yield pool
        await pool.close()


@pytest.fixture()
async def persistence(persistence_pool: PersistencePool) -> CasePersistence:
    return CasePersistence(persistence_pool)


class TestCasePersistenceIntegration:
    async def test_create_and_get_case(self, persistence: CasePersistence) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
        )
        await persistence.create_case(case)

        fetched = await persistence.get_case(case.case_id)
        assert fetched is not None
        assert fetched.case_id == case.case_id
        assert fetched.status == "new"
        assert fetched.version == 1

    async def test_update_case_optimistic_concurrency(self, persistence: CasePersistence) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="alert", raw_payload={"severity": "high"}),
        )
        await persistence.create_case(case)

        new_version = await persistence.update_case(case.case_id, "scented", expected_version=1)
        assert new_version == 2

        with pytest.raises(VersionConflictError):
            await persistence.update_case(case.case_id, "decision", expected_version=1)

    async def test_create_and_get_branch(self, persistence: CasePersistence) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="hunt_query", raw_payload={"query": "suspicious logins"}),
        )
        await persistence.create_case(case)

        branch = BranchState(
            branch_id=str(uuid.uuid4()),
            case_id=case.case_id,
            spec=BranchSpec(
                hypothesis=Hypothesis(description="Lateral movement", confidence=Confidence.STRONG),
                created_by="tracker",
            ),
        )
        await persistence.create_branch(branch)

        fetched = await persistence.get_branch(branch.branch_id)
        assert fetched is not None
        assert fetched.branch_id == branch.branch_id
        assert fetched.case_id == case.case_id
        assert fetched.status == "open"

    async def test_branch_optimistic_concurrency(self, persistence: CasePersistence) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="ioc", raw_payload={"value": "evil.com"}),
        )
        await persistence.create_case(case)

        branch = BranchState(
            branch_id=str(uuid.uuid4()),
            case_id=case.case_id,
            spec=BranchSpec(
                hypothesis=Hypothesis(description="C2 beacon", confidence=Confidence.PLAUSIBLE),
                created_by="tracker",
            ),
        )
        await persistence.create_branch(branch)

        new_version = await persistence.update_branch(
            branch.branch_id, "closed", expected_version=1
        )
        assert new_version == 2

        with pytest.raises(VersionConflictError):
            await persistence.update_branch(branch.branch_id, "merged", expected_version=1)

    async def test_create_and_list_hypotheses(self, persistence: CasePersistence) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="anomaly", raw_payload={"metric": "cpu_spike"}),
        )
        await persistence.create_case(case)

        branch = BranchState(
            branch_id=str(uuid.uuid4()),
            case_id=case.case_id,
            spec=BranchSpec(
                hypothesis=Hypothesis(description="Root", confidence=Confidence.WEAK),
                created_by="alpha",
            ),
        )
        await persistence.create_branch(branch)

        await persistence.create_hypothesis(
            Hypothesis(description="H1", confidence=Confidence.PLAUSIBLE),
            branch.branch_id,
        )
        await persistence.create_hypothesis(
            Hypothesis(description="H2", confidence=Confidence.STRONG),
            branch.branch_id,
        )

        hypotheses = await persistence.list_hypotheses_for_branch(branch.branch_id)
        assert len(hypotheses) == 2
        assert {h.description for h in hypotheses} == {"H1", "H2"}
