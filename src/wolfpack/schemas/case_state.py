"""Case and branch state aggregates."""

from datetime import UTC, datetime

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
    parent_branch_id: str | None = Field(
        default=None, description="Parent branch (NULL for root)."
    )
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
    status: str = Field(
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
    status: str = Field(
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
    overall_confidence: Confidence | None = Field(
        default=None,
        description="Closer-assessed overall confidence (set at verdict time).",
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
