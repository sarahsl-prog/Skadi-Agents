"""Unit tests for the hunt orchestration graph."""

import uuid
from typing import Any

from wolfpack.orchestrator.graph import build_hunt_graph
from wolfpack.orchestrator.stubs import (
    stub_alpha,
    stub_closer,
    stub_flanker,
    stub_review,
    stub_tracker,
)
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed


class TestGraphCompilation:
    """Prove the graph topology is correct."""

    def test_graph_compiles(self) -> None:
        graph = build_hunt_graph()
        assert graph is not None

    def test_mermaid_drawing_does_not_raise(self) -> None:
        graph = build_hunt_graph()
        mermaid = graph.get_graph().draw_mermaid()
        assert "alpha_dispatcher" in mermaid
        assert "tracker" in mermaid
        assert "flanker" in mermaid
        assert "closer" in mermaid
        assert "review" in mermaid

    def test_all_nodes_present(self) -> None:
        graph = build_hunt_graph()
        nodes = set(graph.get_graph().nodes.keys())
        expected = {
            "alpha_dispatcher",
            "tracker",
            "flanker",
            "closer",
            "review",
            "scribe_after_alpha",
            "scribe_after_tracker",
            "scribe_after_flanker",
            "scribe_after_closer",
            "__start__",
            "__end__",
        }
        assert expected.issubset(nodes)


class TestStubHappyPath:
    """End-to-end flow with deterministic stubs."""

    def test_seed_to_closed_case(self) -> None:
        seed = Seed(type="ioc", raw_payload={"value": "10.0.0.1"})
        case_id = str(uuid.uuid4())
        initial_state: dict[str, Any] = {
            "case_id": case_id,
            "seed": seed,
        }

        graph = build_hunt_graph()
        result = graph.invoke(initial_state)

        assert result["case_id"] == case_id
        assert result["status"] == "closed"
        assert result["verdict_decision"] == "BENIGN"
        assert result["overall_confidence"] == Confidence.PLAUSIBLE
        assert result["review_decision"] == "approved"

    def test_tracker_routes_to_closer_when_confidence_high(self) -> None:
        """tracker_confidence == PLAUSIBLE (3) should skip flanker."""
        seed = Seed(type="alert", raw_payload={})
        state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.PLAUSIBLE,
        )
        graph = build_hunt_graph()
        result = graph.invoke(state.model_dump())
        assert result["status"] == "closed"

    def test_tracker_routes_to_flanker_when_confidence_low(self) -> None:
        """tracker_confidence < PLAUSIBLE should hit flanker."""
        seed = Seed(type="alert", raw_payload={})
        state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.WEAK,
        )
        graph = build_hunt_graph()
        result = graph.invoke(state.model_dump())
        assert result["status"] == "closed"


class TestStubFunctions:
    """Direct unit tests for each deterministic stub."""

    def test_stub_alpha_creates_branch(self) -> None:
        seed = Seed(type="ioc", raw_payload={})
        state = CaseState(case_id=str(uuid.uuid4()), seed=seed)
        updates = stub_alpha(state)
        assert updates["status"] == "scented"
        assert len(updates["branches"]) == 1

    def test_stub_tracker_returns_plausible(self) -> None:
        seed = Seed(type="ioc", raw_payload={})
        state = CaseState(case_id=str(uuid.uuid4()), seed=seed)
        updates = stub_tracker(state)
        assert updates["tracker_confidence"] == Confidence.PLAUSIBLE
        assert len(updates["hypotheses"]) == 1

    def test_stub_flanker_returns_empty_branches(self) -> None:
        seed = Seed(type="ioc", raw_payload={})
        state = CaseState(case_id=str(uuid.uuid4()), seed=seed)
        updates = stub_flanker(state)
        assert updates["flanker_confidence"] == Confidence.WEAK

    def test_stub_closer_sets_verdict(self) -> None:
        seed = Seed(type="ioc", raw_payload={})
        state = CaseState(case_id=str(uuid.uuid4()), seed=seed)
        updates = stub_closer(state)
        assert updates["verdict_decision"] == "BENIGN"
        assert updates["status"] == "review"

    def test_stub_review_auto_approves(self) -> None:
        seed = Seed(type="ioc", raw_payload={})
        state = CaseState(case_id=str(uuid.uuid4()), seed=seed)
        updates = stub_review(state)
        assert updates["review_decision"] == "approved"
        assert updates["status"] == "closed"


class TestGraphWithInjectedNodes:
    """Prove the factory accepts real agent implementations."""

    def test_custom_alpha_is_invoked(self) -> None:
        called = False

        def custom_alpha(state: CaseState) -> dict[str, Any]:
            nonlocal called
            called = True
            return {"status": "scented"}

        seed = Seed(type="ioc", raw_payload={})
        graph = build_hunt_graph(use_stubs=True, alpha=custom_alpha)
        graph.invoke({"case_id": str(uuid.uuid4()), "seed": seed})
        assert called
