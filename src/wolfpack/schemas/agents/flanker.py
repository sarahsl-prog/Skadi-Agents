"""Flanker agent I/O models."""

from pydantic import BaseModel, Field

from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis


class FlankerInput(BaseModel):
    """Input to the Flanker agent.

    Flanker performs lateral pivots across hosts, users, DNS, and
    email to find side signals that may warrant a new branch.
    """

    case_id: str = Field(..., description="Case to investigate.")
    branch_id: str = Field(..., description="Branch to pivot from.")
    entities: list[Entity] = Field(
        default_factory=list, description="Entities to use as pivot points."
    )
    hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="Current hypotheses to validate or extend."
    )


class FlankerOutput(BaseModel):
    """Output from the Flanker agent.

    Flanker may emit updated entities, new hypotheses, evidence,
    and optionally a list of new branches to create.
    """

    updated_entities: list[Entity] = Field(
        default_factory=list, description="Entities discovered via lateral pivot."
    )
    new_hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="Hypotheses generated from pivots."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Evidence collected during pivoting."
    )
    branches_to_create: list[BranchSpec] = Field(
        default_factory=list,
        description="New branches that warrant independent investigation.",
    )
    flanker_confidence: Confidence = Field(
        ..., description="Flanker's confidence in the lateral findings."
    )
    significant_findings: bool = Field(
        default=False,
        description="Whether Flanker produced materially new entities, pivots, or hypothesis updates.",
    )
