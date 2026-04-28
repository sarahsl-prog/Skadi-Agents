"""Async persistence helpers with optimistic concurrency control."""

from __future__ import annotations

import json
import uuid

import asyncpg

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


class VersionConflictError(Exception):
    """Raised when an optimistic-concurrency check fails."""


class PersistencePool:
    """Manages an asyncpg connection pool backed by ``PostgresConfig``."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def acquire(self) -> asyncpg.Connection:
        if self._pool is None:
            await self.connect()
        if self._pool is None:  # pragma: no cover
            raise RuntimeError("Failed to create connection pool")
        return await self._pool.acquire()

    async def release(self, conn: asyncpg.Connection) -> None:
        if self._pool is not None:
            await self._pool.release(conn)


class CasePersistence:
    """Async CRUD for ``CaseState`` and ``BranchState``."""

    def __init__(self, pool: PersistencePool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------ #
    # Cases
    # ------------------------------------------------------------------ #

    async def create_case(self, case: CaseState) -> None:
        """Insert a new case row."""
        conn = await self._pool.acquire()
        try:
            await conn.execute(
                """
                INSERT INTO wolfpack.cases (id, seed, status, version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                case.case_id,
                json.dumps(case.seed.model_dump()),
                case.status,
                case.version,
                case.created_at,
                case.updated_at,
            )
        finally:
            await self._pool.release(conn)

    async def get_case(self, case_id: str) -> CaseState | None:
        """Fetch a case by ID (without branches)."""
        conn = await self._pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT id, seed, status, version, created_at, updated_at "
                "FROM wolfpack.cases WHERE id = $1",
                case_id,
            )
            if row is None:
                return None
            seed_data = row["seed"]
            if isinstance(seed_data, str):
                seed_data = json.loads(seed_data)
            return CaseState(
                case_id=str(row["id"]),
                seed=Seed.model_validate(seed_data),
                status=row["status"],
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            await self._pool.release(conn)

    async def update_case(
        self, case_id: str, status: str, expected_version: int
    ) -> int:
        """Optimistically update case status.

        Returns the new version on success.
        Raises ``VersionConflictError`` if the version has changed.
        """
        conn = await self._pool.acquire()
        try:
            result = await conn.fetchrow(
                """
                UPDATE wolfpack.cases
                SET status = $1, version = version + 1, updated_at = NOW()
                WHERE id = $2 AND version = $3
                RETURNING version
                """,
                status,
                case_id,
                expected_version,
            )
            if result is None:
                raise VersionConflictError(
                    f"Case {case_id} version {expected_version} is stale"
                )
            return int(result["version"])
        finally:
            await self._pool.release(conn)

    # ------------------------------------------------------------------ #
    # Branches
    # ------------------------------------------------------------------ #

    async def create_branch(self, branch: BranchState) -> None:
        """Insert a new branch row."""
        conn = await self._pool.acquire()
        try:
            await conn.execute(
                """
                INSERT INTO wolfpack.branches
                (id, case_id, parent_branch_id, hypothesis, depth, status, version, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                branch.branch_id,
                branch.case_id,
                branch.parent_branch_id,
                json.dumps(branch.spec.model_dump()),
                branch.spec.depth,
                branch.status,
                branch.version,
                branch.created_at,
            )
        finally:
            await self._pool.release(conn)

    async def get_branch(self, branch_id: str) -> BranchState | None:
        """Fetch a branch by ID."""
        conn = await self._pool.acquire()
        try:
            row = await conn.fetchrow(
                "SELECT id, case_id, parent_branch_id, hypothesis, depth, "
                "status, version, created_at FROM wolfpack.branches WHERE id = $1",
                branch_id,
            )
            if row is None:
                return None
            hyp_data = row["hypothesis"]
            if isinstance(hyp_data, str):
                hyp_data = json.loads(hyp_data)
            return BranchState(
                branch_id=str(row["id"]),
                case_id=str(row["case_id"]),
                parent_branch_id=(
                    str(row["parent_branch_id"]) if row["parent_branch_id"] else None
                ),
                spec=BranchSpec.model_validate(hyp_data),
                status=row["status"],
                version=row["version"],
                created_at=row["created_at"],
            )
        finally:
            await self._pool.release(conn)

    async def update_branch(
        self, branch_id: str, status: str, expected_version: int
    ) -> int:
        """Optimistically update branch status.

        Returns the new version on success.
        Raises ``VersionConflictError`` if the version has changed.
        """
        conn = await self._pool.acquire()
        try:
            result = await conn.fetchrow(
                """
                UPDATE wolfpack.branches
                SET status = $1, version = version + 1
                WHERE id = $2 AND version = $3
                RETURNING version
                """,
                status,
                branch_id,
                expected_version,
            )
            if result is None:
                raise VersionConflictError(
                    f"Branch {branch_id} version {expected_version} is stale"
                )
            return int(result["version"])
        finally:
            await self._pool.release(conn)

    # ------------------------------------------------------------------ #
    # Hypotheses
    # ------------------------------------------------------------------ #

    async def create_hypothesis(self, hypothesis: Hypothesis, branch_id: str) -> str:
        """Insert a hypothesis and return its generated UUID."""
        conn = await self._pool.acquire()
        try:
            hypothesis_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO wolfpack.hypotheses
                (id, branch_id, description, confidence, status, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                hypothesis_id,
                branch_id,
                hypothesis.description,
                int(hypothesis.confidence),
                hypothesis.status,
            )
            return hypothesis_id
        finally:
            await self._pool.release(conn)

    async def list_hypotheses_for_branch(self, branch_id: str) -> list[Hypothesis]:
        """Fetch all hypotheses for a branch."""
        conn = await self._pool.acquire()
        try:
            rows = await conn.fetch(
                "SELECT description, confidence, status FROM wolfpack.hypotheses "
                "WHERE branch_id = $1",
                branch_id,
            )
            return [
                Hypothesis(
                    description=row["description"],
                    confidence=Confidence(row["confidence"]),
                    status=row["status"],
                )
                for row in rows
            ]
        finally:
            await self._pool.release(conn)
