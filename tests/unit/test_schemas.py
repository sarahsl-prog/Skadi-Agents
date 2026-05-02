"""Unit tests for Pydantic domain models."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from wolfpack.schemas.agents.alpha import AlphaOutput
from wolfpack.schemas.agents.closer import CloserOutput
from wolfpack.schemas.agents.flanker import FlankerOutput
from wolfpack.schemas.agents.scribe import ScribeInput
from wolfpack.schemas.agents.tracker import TrackerOutput
from wolfpack.schemas.branch import BranchSpec
from wolfpack.schemas.case_state import BranchState, CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.graph_state import GraphState
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


class TestConfidence:
    @pytest.mark.parametrize("value,expected", [
        (1, Confidence.COINCIDENCE),
        (2, Confidence.WEAK),
        (3, Confidence.PLAUSIBLE),
        (4, Confidence.STRONG),
        (5, Confidence.HIGH_FIDELITY),
    ])
    def test_ordinal_values(self, value: int, expected: Confidence) -> None:
        assert Confidence(value) is expected

    def test_out_of_bounds_raises(self) -> None:
        with pytest.raises(ValueError):
            Confidence(0)
        with pytest.raises(ValueError):
            Confidence(6)

    def test_int_enum_comparable(self) -> None:
        assert Confidence.PLAUSIBLE > Confidence.WEAK
        assert Confidence.STRONG >= Confidence.STRONG


class TestSeed:
    def test_minimal(self) -> None:
        seed = Seed(type="ioc", raw_payload={"value": "192.0.2.1"})
        assert seed.type == "ioc"
        assert seed.metadata == {}

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Seed(type="invalid", raw_payload={})

    def test_round_trip(self) -> None:
        seed = Seed(type="alert", raw_payload={"severity": "high"}, metadata={"src": "siem"})
        data = seed.model_dump()
        restored = Seed.model_validate(data)
        assert restored == seed


class TestEntity:
    def test_minimal(self) -> None:
        entity = Entity(type="ip", value="192.0.2.1")
        assert entity.type == "ip"
        assert entity.context == {}

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            Entity(type="invalid", value="x")


class TestEvidenceRef:
    def test_minimal(self) -> None:
        ref = EvidenceRef(source_type="syslog", source_id="evt-123")
        assert ref.content_hash is None
        assert ref.timestamp <= datetime.now(UTC)

    def test_round_trip(self) -> None:
        ref = EvidenceRef(
            source_type="crowdstrike",
            source_id="det-456",
            content_hash="a" * 64,
            metadata={"host": "srv-01"},
        )
        restored = EvidenceRef.model_validate(ref.model_dump())
        assert restored == ref


class TestHypothesis:
    def test_minimal(self) -> None:
        h = Hypothesis(
            description="Test hypothesis",
            confidence=Confidence.PLAUSIBLE,
        )
        assert h.status == "open"
        assert h.evidence_refs == []

    def test_with_evidence(self) -> None:
        ref = EvidenceRef(source_type="okta", source_id="evt-789")
        h = Hypothesis(
            description="Lateral movement via RDP",
            confidence=Confidence.STRONG,
            evidence_refs=[ref],
            branch_id=str(uuid.uuid4()),
        )
        assert len(h.evidence_refs) == 1


class TestBranchSpec:
    def test_root_branch(self) -> None:
        spec = BranchSpec(
            hypothesis=Hypothesis(
                description="Root hypothesis",
                confidence=Confidence.PLAUSIBLE,
            ),
            created_by="alpha",
        )
        assert spec.parent_branch_id is None
        assert spec.depth == 0

    def test_child_branch(self) -> None:
        parent_id = str(uuid.uuid4())
        spec = BranchSpec(
            parent_branch_id=parent_id,
            hypothesis=Hypothesis(
                description="Child hypothesis",
                confidence=Confidence.WEAK,
            ),
            depth=1,
            created_by="flanker",
        )
        assert spec.parent_branch_id == parent_id
        assert spec.depth == 1

    def test_negative_depth_raises(self) -> None:
        with pytest.raises(ValidationError):
            BranchSpec(
                hypothesis=Hypothesis(description="bad", confidence=Confidence.WEAK),
                depth=-1,
                created_by="test",
            )


class TestBranchState:
    def test_defaults(self) -> None:
        bs = BranchState(
            branch_id=str(uuid.uuid4()),
            case_id=str(uuid.uuid4()),
            spec=BranchSpec(
                hypothesis=Hypothesis(description="h", confidence=Confidence.WEAK),
                created_by="alpha",
            ),
        )
        assert bs.version == 1
        assert bs.status == "open"


class TestCaseState:
    def test_aggregate(self) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
        )
        assert case.status == "new"
        assert case.overall_confidence is None
        assert case.branches == []


class TestGraphState:
    def test_is_case_state(self) -> None:
        assert GraphState is CaseState


class TestAlphaIO:
    def test_output_default_next_agent(self) -> None:
        case = CaseState(
            case_id=str(uuid.uuid4()),
            seed=Seed(type="alert", raw_payload={}),
        )
        out = AlphaOutput(case_state=case)
        assert out.next_agent == "tracker"


class TestTrackerIO:
    def test_output_structured(self) -> None:
        out = TrackerOutput(
            tracker_confidence=Confidence.STRONG,
            hypotheses=[
                Hypothesis(description="Suspicious RDP", confidence=Confidence.STRONG)
            ],
        )
        assert out.tracker_confidence == Confidence.STRONG
        assert len(out.hypotheses) == 1


class TestFlankerIO:
    def test_branches_to_create(self) -> None:
        out = FlankerOutput(
            flanker_confidence=Confidence.PLAUSIBLE,
            branches_to_create=[
                BranchSpec(
                    hypothesis=Hypothesis(description="DNS pivot", confidence=Confidence.WEAK),
                    created_by="flanker",
                )
            ],
        )
        assert len(out.branches_to_create) == 1


class TestCloserIO:
    def test_verdict(self) -> None:
        out = CloserOutput(decision="malicious", confidence=Confidence.HIGH_FIDELITY)
        assert out.decision == "malicious"
        assert out.confidence == Confidence.HIGH_FIDELITY


class TestScribeIO:
    def test_ledger_event(self) -> None:
        inp = ScribeInput(
            case_id=str(uuid.uuid4()),
            event_type="agent_action",
            payload={"agent": "tracker", "action": "query_telemetry"},
        )
        assert inp.branch_id is None
        assert inp.agent_run_id is None

    def test_invalid_event_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            ScribeInput(
                case_id=str(uuid.uuid4()),
                event_type="invalid_event",
                payload={},
            )
