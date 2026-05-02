"""Branch-explosion controls for the hunt orchestrator.

Enforces per-case limits on branch depth and branch count.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from wolfpack.config.settings import BranchBudgetConfig, Settings


@dataclass(frozen=True)
class BudgetRemaining:
    """Snapshot of remaining budget for a case."""

    branches_remaining: int
    depth_remaining: int


class BranchBudget:
    """Enforce per-case branch budget constraints.

    Budget state is held in-memory (a ``dict``) for V1.  In production
    this should be backed by Redis or Postgres so that concurrent
    graph workers share the same counters and survive process restarts.
    """

    def __init__(self, config: BranchBudgetConfig | None = None) -> None:
        if config is None:
            config = Settings().branch_budget
        self._config = config
        self._state: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()

    def _ensure(self, case_id: str) -> dict[str, int]:
        if case_id not in self._state:
            self._state[case_id] = {
                "branch_count": 0,
            }
        return self._state[case_id]

    async def check(
        self,
        case_id: str,
        branch_depth: int,
        branches_so_far: int | None = None,
    ) -> bool:
        """Return ``True`` if the proposed branch is within budget.

        Args:
            case_id: Case identifier.
            branch_depth: Proposed branch depth (0 = root).
            branches_so_far: Override branch count (uses internal counter if ``None``).
        """
        async with self._lock:
            state = self._ensure(case_id)
            current_count = branches_so_far if branches_so_far is not None else state["branch_count"]

            if branch_depth > self._config.max_depth:
                return False
            if current_count >= self._config.max_branches_per_case:
                return False
            return True

    async def remaining(
        self,
        case_id: str,
        branches_so_far: int | None = None,
    ) -> BudgetRemaining:
        """Return the remaining budget for *case_id*."""
        async with self._lock:
            state = self._ensure(case_id)
            current_count = branches_so_far if branches_so_far is not None else state["branch_count"]

            return BudgetRemaining(
                branches_remaining=max(0, self._config.max_branches_per_case - current_count),
                depth_remaining=self._config.max_depth,
            )

    def consume(
        self,
        case_id: str,
        *,
        branches: int = 0,
    ) -> None:
        """Consume budget for *case_id*.

        Called by the graph after a branch is created so that subsequent
        checks see the updated counter.
        """
        # Synchronous consume for backward compatibility with sync call sites.
        # In async context, prefer check_and_consume.
        state = self._ensure(case_id)
        state["branch_count"] += branches

    async def check_and_consume(
        self,
        case_id: str,
        branch_depth: int,
        branches: int = 1,
    ) -> bool:
        """Atomically check budget and consume if within limits.

        Returns ``True`` if the budget check passed and consumption
        succeeded.  This method is thread-safe for the in-memory
        implementation.  For multi-process deployments back this with
        Redis ``INCR`` or Postgres ``UPDATE ... RETURNING``.
        """
        async with self._lock:
            state = self._ensure(case_id)
            current_count = state["branch_count"]

            if branch_depth > self._config.max_depth:
                return False
            if current_count >= self._config.max_branches_per_case:
                return False

            state["branch_count"] += branches
            return True
