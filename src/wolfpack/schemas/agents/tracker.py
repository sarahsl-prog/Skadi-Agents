"""Tracker agent I/O models."""

from pydantic import BaseModel, Field

from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis


class TrackerInput(BaseModel):
    """Input to the Tracker agent.

    Tracker is tasked with finding an initial credible scent by
    querying telemetry adapters and threat intel.
    """

    case_id: str = Field(..., description="Case to investigate.")
    branch_id: str = Field(..., description="Branch to focus on.")
    entities: list[Entity] = Field(
        default_factory=list, description="Known entities to seed queries."
    )


class TrackerOutput(BaseModel):
    """Output from the Tracker agent.

    Tracker emits new hypotheses, updated entity lists, evidence
    references, and a confidence ordinal.
    """

    hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="New or updated hypotheses."
    )
    updated_entities: list[Entity] = Field(
        default_factory=list, description="Entities discovered or enriched."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Evidence collected during the run."
    )
    tracker_confidence: Confidence = Field(
        ..., description="Tracker's overall confidence in the findings."
    )
    reasoning: str = Field(
        default="", description="Concise human-readable reasoning for the findings."
    )
