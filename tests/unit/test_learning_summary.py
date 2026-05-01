"""Unit tests for case summary formatting."""

from __future__ import annotations

import datetime as dt
from typing import Any

from wolfpack.learning.summary import CaseSummary, EntitySummary, format_case_summary
from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed
from wolfpack.schemas.verdict import VerdictPacket


class TestEntitySummary:
    """Pseudonymisation and basic properties."""

    def test_from_entity(self) -> None:
        entity = Entity(type="ip", value="10.0.0.1")
        summary = EntitySummary.from_entity(entity)
        assert summary.type == "ip"
        assert summary.pseudonym.startswith("ip-")

    def test_consistent(self) -> None:
        entity = Entity(type="host", value="web-01")
        s1 = EntitySummary.from_entity(entity)
        s2 = EntitySummary.from_entity(entity)
        assert s1.pseudonym == s2.pseudonym


class TestCaseSummary:
    """Schema validation."""

    def test_minimal(self) -> None:
        summary = CaseSummary(
            case_id="c-1",
            seed_type="ioc",
            seed_summary="10.0.0.1",
            verdict="BENIGN",
            confidence=Confidence.WEAK,
            branches=1,
            duration_hours=0.5,
            narrative="Case narrative",
        )
        assert summary.case_id == "c-1"
        assert summary.false_positive is True

    def test_to_rag_document(self) -> None:
        summary = CaseSummary(
            case_id="c-2",
            seed_type="alert",
            seed_summary="Phish",
            verdict="MALICIOUS",
            confidence=Confidence.STRONG,
            branches=2,
            duration_hours=1.0,
            narrative="Narrative content",
            key_findings=["f1", "f2"],
        )
        doc = summary.to_rag_document()
        assert doc["id"] == "c-2"
        assert doc["content"] == "Narrative content"
        assert doc["metadata"]["verdict"] == "MALICIOUS"
        assert doc["metadata"]["branches"] == 2


class TestFormatCaseSummary:
    """End-to-end formatting from case state."""

    def _make_case(self, **overrides: Any) -> CaseState:
        now = dt.datetime.now(dt.UTC)
        return CaseState(
            case_id=overrides.get("case_id", "c-1"),
            seed=Seed(
                type=overrides.get("seed_type", "ioc"),
                raw_payload=overrides.get("raw_payload", {"value": "10.0.0.1"}),
            ),
            branches=overrides.get("branches", []),
            verdict_decision=overrides.get("verdict_decision"),
            overall_confidence=overrides.get("overall_confidence"),
            created_at=overrides.get("created_at", now),
            updated_at=overrides.get("updated_at", now),
        )

    def test_basic(self) -> None:
        case = self._make_case()
        verdict = VerdictPacket(decision="BENIGN", confidence=Confidence.PLAUSIBLE)
        summary = format_case_summary(case, verdict=verdict)
        assert summary.case_id == "c-1"
        assert summary.seed_type == "ioc"
        assert "10.0.0.1" in summary.seed_summary
        assert summary.branches == 0
        assert summary.duration_hours == 0.0
        assert summary.false_positive is True

    def test_from_case_state_fields(self) -> None:
        case = self._make_case(
            verdict_decision="malicious",
            overall_confidence=Confidence.STRONG,
        )
        summary = format_case_summary(case)
        assert summary.verdict == "MALICIOUS"
        assert summary.confidence == Confidence.STRONG

    def test_attack_techniques_from_evidence_metadata(self) -> None:
        case = self._make_case()
        case.evidence_refs = [
            EvidenceRef(
                source_type="syslog",
                source_id="e1",
                metadata={"technique": "T1566"},
            ),
            EvidenceRef(
                source_type="firewall",
                source_id="e2",
                metadata={"tags": "T1566 T1078"},
            ),
        ]
        summary = format_case_summary(case)
        assert "T1566" in summary.attack_techniques
        assert "T1078" in summary.attack_techniques

    def test_entities_deduplicated(self) -> None:
        case = self._make_case()
        case.branches = [
            BranchState(
                branch_id="b1",
                case_id="c-1",
                spec=BranchSpec(
                    hypothesis=Hypothesis(description="h1", confidence=Confidence.WEAK),
                    created_by="alpha",
                ),
                entities=[
                    Entity(type="ip", value="10.0.0.1"),
                    Entity(type="ip", value="10.0.0.1"),
                    Entity(type="host", value="web-01"),
                ],
            ),
        ]
        summary = format_case_summary(case)
        assert len(summary.entities) == 2
        types = {e.type for e in summary.entities}
        assert types == {"ip", "host"}

    def test_key_findings_from_hypotheses(self) -> None:
        case = self._make_case()
        case.hypotheses = [
            Hypothesis(description="Initial compromise", confidence=Confidence.PLAUSIBLE),
        ]
        case.branches = [
            BranchState(
                branch_id="b1",
                case_id="c-1",
                spec=BranchSpec(
                    hypothesis=Hypothesis(
                        description="Lateral movement",
                        confidence=Confidence.STRONG,
                    ),
                    created_by="flanker",
                ),
            ),
        ]
        summary = format_case_summary(case)
        assert "Initial compromise" in summary.key_findings
        assert "Lateral movement" in summary.key_findings

    def test_narrative_contains_seed_and_reasoning(self) -> None:
        case = self._make_case()
        verdict = VerdictPacket(
            decision="MALICIOUS",
            confidence=Confidence.STRONG,
            reasoning_summary="Confirmed malware beaconing.",
        )
        summary = format_case_summary(case, verdict=verdict)
        assert case.case_id in summary.narrative
        assert "Confirmed malware beaconing." in summary.narrative

    def test_empty_evidence(self) -> None:
        case = self._make_case()
        summary = format_case_summary(case)
        assert summary.attack_techniques == []

    def test_no_branches(self) -> None:
        case = self._make_case()
        summary = format_case_summary(case)
        assert summary.branches == 0
        assert summary.duration_hours == 0.0

    def test_non_benign_false_positive(self) -> None:
        case = self._make_case(verdict_decision="malicious")
        summary = format_case_summary(case)
        assert summary.false_positive is False
