"""Hypothesis models produced by Tracker and Flanker."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.evidence import EvidenceRef


class Hypothesis(BaseModel):
    """A hypothesis links entities to a proposed explanation.

    Hypotheses are created by Tracker (initial scent) and Flanker
    (lateral pivot).  They carry a confidence ordinal and a list of
    evidence references so that the Closer can assemble a verdict.
    """

    description: str = Field(..., description="Human-readable statement of the hypothesis.")
    confidence: Confidence = Field(..., description="Agent-assessed confidence (1-5).")
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Pointers to supporting evidence."
    )
    status: Literal["open", "confirmed", "rejected", "superseded"] = Field(
        default="open",
        description="Lifecycle state: open, confirmed, rejected, superseded.",
    )
    branch_id: str | None = Field(
        default=None,
        description="Branch that owns this hypothesis (NULL for case-level).",
    )
