"""Structured case summary format for the learning queue.

Transforms a closed case into a narrative-rich, filterable summary
that can be indexed by the case-history RAG pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.verdict import VerdictPacket

DecisionType = Literal["MALICIOUS", "BENIGN", "INCONCLUSIVE", "NEEDS_MORE_INFO"]


class EntitySummary(BaseModel):
    """Pseudonymised entity entry suitable for institutional memory."""

    type: str = Field(..., description="Entity telemetry category.")
    pseudonym: str = Field(
        ..., description="Deterministic pseudonym derived from the raw value."
    )

    @classmethod
    def from_entity(cls, entity: Entity, salt: str = "wolfpack-learning") -> EntitySummary:
        digest = hashlib.sha256(f"{salt}:{entity.value}".encode()).hexdigest()[:12]
        return cls(type=entity.type, pseudonym=f"{entity.type}-{digest}")


class CaseSummary(BaseModel):
    """Structured, machine-indexable summary of a closed hunt case.

    The *narrative* field targets semantic search, while the remaining
    fields are indexed as metadata for filtering.
    """

    case_id: str = Field(..., description="Stable case identifier.")
    seed_type: str = Field(..., description="Type of seed that started the case.")
    seed_summary: str = Field(
        ..., description="Human-readable summary of the original seed."
    )
    verdict: str = Field(
        ..., description="Final verdict decision (MALICIOUS/BENIGN/INCONCLUSIVE/NEEDS_MORE_INFO)."
    )
    confidence: Confidence = Field(..., description="Final confidence ordinal.")
    attack_techniques: list[str] = Field(
        default_factory=list, description="ATT&CK technique IDs referenced."
    )
    entities: list[EntitySummary] = Field(
        default_factory=list, description="Key pseudonymised entities."
    )
    branches: int = Field(..., description="Number of branches investigated.")
    duration_hours: float = Field(
        ..., description="Elapsed hours from case creation to closure."
    )
    narrative: str = Field(
        ...,
        description="Human-readable case narrative (primary target for semantic retrieval).",
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Bullet-point list of key findings.",
    )
    false_positive: bool = Field(
        default=False, description="Whether the case was closed as benign."
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_false_positive(cls, data: Any) -> Any:
        if isinstance(data, dict):
            verdict = data.get("verdict", "")
            if isinstance(verdict, str) and verdict.upper() == "BENIGN":
                data["false_positive"] = True
        return data

    def to_rag_document(self) -> dict[str, Any]:
        """Return a flat representation suitable for :class:`RAGDocument` creation."""
        return {
            "id": self.case_id,
            "content": self.narrative,
            "metadata": {
                "seed_type": self.seed_type,
                "verdict": self.verdict,
                "confidence": int(self.confidence),
                "attack_techniques": self.attack_techniques,
                "entities": [e.model_dump() for e in self.entities],
                "branches": self.branches,
                "duration_hours": self.duration_hours,
                "key_findings": self.key_findings,
                "false_positive": self.false_positive,
            },
        }


def format_case_summary(
    case_state: CaseState,
    verdict: VerdictPacket | None = None,
    evidence: list[EvidenceRef] | None = None,
) -> CaseSummary:
    """Produce a :class:`CaseSummary` from a closed case.

    Args:
        case_state: aggregate case state (branches, hypotheses, entities).
        verdict: optional verdict packet emitted by the Closer agent.
        evidence: optional list of evidence refs (falls back to case_state refs).
    """
    now = datetime.now(UTC)
    evidence_list = evidence if evidence is not None else case_state.evidence_refs

    # Seed summary — human readable
    raw_payload = case_state.seed.raw_payload or {}
    seed_summary_parts: list[str] = []
    if "value" in raw_payload:
        seed_summary_parts.append(str(raw_payload["value"]))
    if "description" in raw_payload:
        seed_summary_parts.append(str(raw_payload["description"]))
    if not seed_summary_parts:
        seed_summary_parts.append(str(case_state.seed.type))
    seed_summary = " — ".join(seed_summary_parts)

    # Verdict / confidence resolution
    verdict_decision: str = verdict.decision if verdict else "INCONCLUSIVE"
    verdict_confidence: Confidence = (
        verdict.confidence if verdict else Confidence.COINCIDENCE
    )
    if case_state.overall_confidence is not None:
        verdict_confidence = case_state.overall_confidence
    if case_state.verdict_decision is not None:
        verdict_decision = case_state.verdict_decision.upper()

    # ATT&CK extraction from evidence metadata
    attack_techniques: set[str] = set()
    for ref in evidence_list:
        tech = ref.metadata.get("technique")
        if tech:
            attack_techniques.add(str(tech))
        # Also check for ATT&CK IDs in description or tags
        for key in ("description", "tags"):
            val = ref.metadata.get(key)
            if val and isinstance(val, str):
                for token in val.split():
                    if token.upper().startswith("T") and token[1:].isdigit():
                        attack_techniques.add(token.upper())

    # Entities (dedup across branches)
    seen: set[str] = set()
    entity_summaries: list[EntitySummary] = []
    for branch in case_state.branches:
        for entity in branch.entities:
            key = f"{entity.type}:{entity.value}"
            if key not in seen:
                seen.add(key)
                entity_summaries.append(EntitySummary.from_entity(entity))

    # Duration
    created = case_state.created_at
    closed = case_state.updated_at or now
    duration_hours = max(
        0.0, (closed - created).total_seconds() / 3600.0
    )

    # Narrative
    narrative_parts: list[str] = [
        f"Case {case_state.case_id} started with a {case_state.seed.type} seed: {seed_summary}.",
        f"Investigated across {len(case_state.branches)} branch(es).",
    ]
    if verdict and verdict.reasoning_summary:
        narrative_parts.append(f"Closer reasoning: {verdict.reasoning_summary}")
    elif case_state.verdict_decision:
        narrative_parts.append(f"Case closed as {case_state.verdict_decision}.")
    narrative = " ".join(narrative_parts)

    # Key findings from hypotheses
    key_findings: list[str] = []
    for hyp in case_state.hypotheses:
        if hyp.description:
            key_findings.append(hyp.description)
    for branch in case_state.branches:
        # Add the hypothesis from branch spec (root hypothesis)
        if branch.spec.hypothesis and branch.spec.hypothesis.description:
            key_findings.append(branch.spec.hypothesis.description)
        for hyp in branch.hypotheses:
            if hyp.description and hyp.description not in key_findings:
                key_findings.append(hyp.description)

    return CaseSummary(
        case_id=case_state.case_id,
        seed_type=case_state.seed.type,
        seed_summary=seed_summary,
        verdict=verdict_decision,
        confidence=verdict_confidence,
        attack_techniques=sorted(attack_techniques),
        entities=entity_summaries,
        branches=len(case_state.branches),
        duration_hours=round(duration_hours, 2),
        narrative=narrative,
        key_findings=key_findings,
        false_positive=(verdict_decision == "BENIGN"),
    )
