"""Verdict packet and policy guardrail schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.evidence import EvidenceRef


class BranchSummary(BaseModel):
    """Summary of a branch in a verdict packet."""

    branch_id: str = Field(..., description="Branch identifier.")
    depth: int = Field(default=0, description="Branch depth from root.")
    hypothesis_summary: str = Field(default="", description="Short hypothesis description.")
    entity_count: int = Field(default=0, description="Number of entities found.")
    evidence_count: int = Field(default=0, description="Number of evidence refs collected.")


class VerdictPacket(BaseModel):
    """Structured verdict emitted by the Closer agent."""

    decision: Literal["MALICIOUS", "BENIGN", "INCONCLUSIVE", "NEEDS_MORE_INFO", "SUSPICIOUS"] = (
        Field(..., description="Final verdict decision.")
    )
    confidence: Confidence = Field(..., description="Closer's confidence in the verdict.")
    next_best_action: str = Field(
        default="",
        description="Recommended next step for the analyst.",
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list, description="Evidence supporting the verdict."
    )
    reasoning_summary: str = Field(
        default="",
        description="Concise human-readable reasoning for the verdict.",
    )
    branch_summaries: list[BranchSummary] = Field(
        default_factory=list,
        description="Summary of each branch in the investigation.",
    )
    policy_applicable: list[str] = Field(
        default_factory=list,
        description="List of policy IDs that apply to this verdict.",
    )


class PolicyGuardrail(BaseModel):
    """A policy guardrail attached to a verdict."""

    id: str = Field(..., description="Unique policy identifier.")
    name: str = Field(..., description="Human-readable policy name.")
    description: str = Field(..., description="What this policy checks for.")
    severity: Literal["info", "warning", "critical"] = Field(
        ..., description="Severity of the guardrail."
    )
    action_required: str | None = Field(
        default=None,
        description="Required action if the policy triggers.",
    )
