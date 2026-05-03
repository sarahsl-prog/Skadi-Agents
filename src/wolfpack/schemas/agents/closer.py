"""Closer agent I/O models."""

from typing import Literal

from pydantic import BaseModel, Field

from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis


class CloserInput(BaseModel):
    """Input to the Closer agent.

    Closer assembles a verdict packet from the case state and all
    collected evidence for analyst review.
    """

    case_id: str = Field(..., description="Case to close.")
    hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="All hypotheses to consider."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="All evidence to cite."
    )


class CloserOutput(BaseModel):
    """Output from the Closer agent.

    Closer emits a verdict packet with a decision, confidence,
    next-best action, and evidence references.
    """

    decision: Literal["MALICIOUS", "BENIGN", "INCONCLUSIVE", "NEEDS_MORE_INFO", "SUSPICIOUS"] = (
        Field(
            ...,
            description="Verdict: MALICIOUS, BENIGN, INCONCLUSIVE, NEEDS_MORE_INFO, or SUSPICIOUS.",
        )
    )
    confidence: Confidence = Field(..., description="Closer's confidence in the verdict.")
    next_best_action: str = Field(default="", description="Recommended next step for the analyst.")
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Evidence supporting the verdict."
    )
    reasoning_summary: str = Field(
        default="", description="Concise human-readable reasoning for the verdict."
    )
