"""Branch creation and management for the hunt orchestrator.

Provides helpers to create :class:`BranchState` rows in Postgres,
link them to parent branches, and publish NATS messages.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from wolfpack.orchestrator.budget import BranchBudget
from wolfpack.orchestrator.bus import NATSClient
from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState
from wolfpack.schemas.persistence import CasePersistence


async def create_branch(
    case_id: str,
    parent_branch_id: str | None,
    hypothesis: Any,
    depth: int,
    created_by: str,
    persistence: CasePersistence,
    nats_client: NATSClient | None = None,
    budget: BranchBudget | None = None,
    branches_so_far: int = 0,
) -> BranchState | None:
    """Create a new branch, persist it, and optionally publish a NATS message.

    Args:
        case_id: Owning case identifier.
        parent_branch_id: Parent branch (``None`` for root).
        hypothesis: A :class:`Hypothesis` or dict describing the branch rationale.
        depth: Branch depth from root (0 = root).
        created_by: Agent or analyst that created the branch.
        persistence: :class:`CasePersistence` for DB operations.
        nats_client: Optional NATS client for publishing ``hunt.branch.created``.
        budget: Optional branch budget to enforce before creation.
        branches_so_far: Number of branches already created for this case.

    Returns:
        The newly created :class:`BranchState`, or ``None`` if the budget
        check fails.
    """
    if budget is not None:
        # Prefer atomic check-and-consume; fall back to separate check
        # when branches_so_far is supplied by the caller.
        if branches_so_far:
            if not await budget.check(case_id, depth, branches_so_far):
                return None
        else:
            if not await budget.check_and_consume(case_id, depth, branches=1):
                return None

    from wolfpack.schemas.hypothesis import Hypothesis

    if isinstance(hypothesis, dict):
        hypothesis = Hypothesis.model_validate(hypothesis)

    spec = BranchSpec(
        parent_branch_id=parent_branch_id,
        hypothesis=hypothesis,
        depth=depth,
        created_by=created_by,
    )

    branch = BranchState(
        branch_id=str(uuid.uuid4()),
        case_id=case_id,
        parent_branch_id=parent_branch_id,
        spec=spec,
        status="open",
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    try:
        await persistence.create_branch(branch)
    except Exception:
        if budget is not None and not branches_so_far:
            await budget.release(case_id, branches=1)
        return None

    if budget is not None and branches_so_far:
        await budget.consume(case_id, branches=1)

    if nats_client is not None and nats_client.connected:
        # Include a sanitized hypothesis summary so the audit trail
        # records *why* the branch was created.
        hyp_summary = ""
        if hypothesis and hasattr(hypothesis, "description"):
            hyp_summary = str(hypothesis.description)[:500]

        await nats_client.publish(
            "hunt.branch.created",
            {
                "branch_id": branch.branch_id,
                "case_id": branch.case_id,
                "parent_branch_id": branch.parent_branch_id,
                "depth": depth,
                "created_by": created_by,
                "timestamp": branch.created_at.isoformat(),
                "hypothesis_summary": hyp_summary,
            },
        )

    return branch


async def list_branches_for_case(
    case_id: str,
    persistence: CasePersistence,
) -> list[BranchState]:
    """Return all branches for *case_id*."""
    return await persistence.list_branches_for_case(case_id)
