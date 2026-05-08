"""Branch-explosion controls for the hunt orchestrator.

Enforces per-case limits on branch depth and branch count.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import asyncpg

from wolfpack.config.settings import BranchBudgetConfig, Settings


@dataclass(frozen=True)
class BudgetRemaining:
    """Snapshot of remaining budget for a case."""

    branches_remaining: int
    depth_remaining: int


class BranchBudget:
    """Enforce per-case branch budget constraints.

    Budget state is backed by Postgres for multi-worker consistency
    and process-restart survival.  When *pool* is ``None`` the class
    falls back to the original in-memory ``dict`` so that tests and
    single-process deployments continue to work.
    """

    def __init__(
        self,
        config: BranchBudgetConfig | None = None,
        pool: asyncpg.Pool | None = None,
    ) -> None:
        if config is None:
            config = Settings().branch_budget
        self._config = config
        self._pool = pool
        self._state: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # In-memory fallback helpers
    # ------------------------------------------------------------------ #

    def _ensure(self, case_id: str) -> dict[str, int]:
        if case_id not in self._state:
            self._state[case_id] = {"branch_count": 0}
        return self._state[case_id]

    # ------------------------------------------------------------------ #
    # Postgres helpers
    # ------------------------------------------------------------------ #

    async def _ensure_table(self) -> None:
        """Create the branch_budget table if it does not exist."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wolfpack.branch_budget (
                    case_id TEXT PRIMARY KEY,
                    branch_count INT NOT NULL DEFAULT 0
                )
                """
            )

    async def _get_count(self, case_id: str) -> int:
        """Return the current branch_count for *case_id* from Postgres."""
        if self._pool is None:
            return self._ensure(case_id)["branch_count"]
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT branch_count FROM wolfpack.branch_budget WHERE case_id = $1",
                case_id,
            )
            return row["branch_count"] if row is not None else 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def check(
        self,
        case_id: str,
        branch_depth: int,
        branches_so_far: int | None = None,
    ) -> bool:
        """Return ``True`` if the proposed branch is within budget."""
        if branch_depth > self._config.max_depth:
            return False

        if branches_so_far is not None:
            current_count = branches_so_far
        else:
            current_count = await self._get_count(case_id)

        return current_count < self._config.max_branches_per_case

    async def remaining(
        self,
        case_id: str,
        branches_so_far: int | None = None,
    ) -> BudgetRemaining:
        """Return the remaining budget for *case_id*."""
        if branches_so_far is not None:
            current_count = branches_so_far
        else:
            current_count = await self._get_count(case_id)

        return BudgetRemaining(
            branches_remaining=max(
                0, self._config.max_branches_per_case - current_count
            ),
            depth_remaining=self._config.max_depth,
        )

    async def release(
        self,
        case_id: str,
        *,
        branches: int = 1,
    ) -> None:
        """Release previously consumed budget for *case_id*."""
        if self._pool is None:
            state = self._ensure(case_id)
            state["branch_count"] = max(0, state["branch_count"] - branches)
            return

        await self._ensure_table()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wolfpack.branch_budget
                SET branch_count = GREATEST(0, branch_count - $2)
                WHERE case_id = $1
                """,
                case_id,
                branches,
            )

    async def consume(
        self,
        case_id: str,
        *,
        branches: int = 1,
    ) -> None:
        """Consume budget for *case_id*."""
        if self._pool is None:
            state = self._ensure(case_id)
            state["branch_count"] += branches
            return

        await self._ensure_table()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO wolfpack.branch_budget (case_id, branch_count)
                VALUES ($1, $2)
                ON CONFLICT (case_id)
                DO UPDATE SET branch_count =
                    wolfpack.branch_budget.branch_count + EXCLUDED.branch_count
                """,
                case_id,
                branches,
            )

    async def check_and_consume(
        self,
        case_id: str,
        branch_depth: int,
        branches: int = 1,
    ) -> bool:
        """Atomically check budget and consume if within limits.

        Returns ``True`` if the budget check passed and consumption
        succeeded.
        """
        if branch_depth > self._config.max_depth:
            return False

        if self._pool is None:
            async with self._lock:
                state = self._ensure(case_id)
                current_count = state["branch_count"]

                if current_count >= self._config.max_branches_per_case:
                    return False

                state["branch_count"] += branches
                return True

        # Postgres atomic path
        await self._ensure_table()
        async with self._pool.acquire() as conn:
            # Ensure row exists first (idempotent)
            await conn.execute(
                """
                INSERT INTO wolfpack.branch_budget (case_id, branch_count)
                VALUES ($1, 0)
                ON CONFLICT (case_id) DO NOTHING
                """,
                case_id,
            )

            # Atomically update if still within limits
            row = await conn.fetchrow(
                """
                UPDATE wolfpack.branch_budget
                SET branch_count = branch_count + $3
                WHERE case_id = $1
                  AND branch_count + $3 <= $2
                RETURNING branch_count
                """,
                case_id,
                self._config.max_branches_per_case,
                branches,
            )

            return row is not None
