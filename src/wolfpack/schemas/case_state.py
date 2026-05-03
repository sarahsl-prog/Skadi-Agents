"""Case and branch state aggregates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


class BranchState(BaseModel):
    """Per-branch mutable sub-state.

    Each branch carries its own ``version`` column so that optimistic
    concurrency can prevent Flanker / Tracker write conflicts during
    parallel work.
    """

    branch_id: str = Field(..., description="Stable branch identifier (UUID).")
    case_id: str = Field(..., description="Owning case identifier.")
    parent_branch_id: str | None = Field(default=None, description="Parent branch (NULL for root).")
    spec: BranchSpec = Field(..., description="Original branch specification.")
    entities: list[Entity] = Field(
        default_factory=list, description="Entities discovered in this branch."
    )
    hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="Hypotheses attached to this branch."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Evidence collected in this branch."
    )
    status: Literal["open", "closed", "merged", "abandoned"] = Field(
        default="open", description="Branch status: open, closed, merged, abandoned."
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Optimistic-concurrency version (incremented on every write).",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC creation timestamp.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC last-update timestamp.",
    )


class CaseState(BaseModel):
    """Aggregate view over a hunt case and all its branches.

    ``CaseState`` is the single source of truth for the LangGraph
    checkpoint.  It is assembled from the ``cases`` row plus all
    related ``branches``, ``hypotheses``, and ``evidence_ledger`` rows.
    """

    case_id: str = Field(..., description="Stable case identifier (UUID).")
    seed: Seed = Field(..., description="Original hunt seed.")
    status: Literal["new", "scented", "shadowing", "decision", "review", "closed"] = Field(
        default="new",
        description="Case lifecycle: new, scented, shadowing, decision, review, closed.",
    )
    branches: list[BranchState] = Field(
        default_factory=list, description="All branches in this case."
    )
    hypotheses: list[Hypothesis] = Field(
        default_factory=list,
        description="Case-level hypotheses (aggregated from branches).",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list,
        description="Case-level evidence (aggregated from branches).",
    )
    tracker_confidence: Confidence | None = Field(
        default=None,
        description="Tracker-assessed confidence (used for routing).",
    )
    flanker_confidence: Confidence | None = Field(
        default=None,
        description="Flanker-assessed confidence (used for routing).",
    )
    re_check_count: int = Field(
        default=0,
        ge=0,
        description="Number of Tracker→Flanker re-check iterations completed.",
    )
    significant_findings: bool = Field(
        default=False,
        description="Whether Flanker produced significant new findings warranting re-check.",
    )
    review_decision: Literal["approved", "escalate", "close_benign", "continue"] | None = Field(
        default=None,
        description="Analyst review decision: approved, escalate, close_benign, continue.",
    )
    verdict_decision: (
        Literal["MALICIOUS", "BENIGN", "INCONCLUSIVE", "NEEDS_MORE_INFO", "SUSPICIOUS"] | None
    ) = Field(
        default=None,
        description="Closer verdict: MALICIOUS, BENIGN, INCONCLUSIVE, NEEDS_MORE_INFO, or SUSPICIOUS.",
    )
    overall_confidence: Confidence | None = Field(
        default=None,
        description="Closer-assessed overall confidence (set at verdict time).",
    )
    review_started_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the case entered review status.",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Optimistic-concurrency version for the case row.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC creation timestamp.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC last-update timestamp.",
    )
