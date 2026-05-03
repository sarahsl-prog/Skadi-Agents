"""Integration tests for Flanker re-check loop and lateral pivots."""

from __future__ import annotations

import uuid
from typing import Any

from wolfpack.orchestrator.graph import build_hunt_graph
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.seed import Seed


class TestReCheckLoopRouting:
    """Graph routing when Tracker confidence is low."""

    def test_low_confidence_routes_to_flanker_then_closer(self) -> None:
        """WEAK confidence → Flanker (no significant findings) → Closer → closed."""

        def weak_tracker(state: CaseState) -> dict[str, Any]:
            return {
                "tracker_confidence": Confidence.WEAK,
                "status": "shadowing",
                "hypotheses": [],
                "evidence_refs": [],
            }

        seed = Seed(type="alert", raw_payload={})
        initial_state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.WEAK,
            re_check_count=0,
        )
        graph = build_hunt_graph(use_stubs=True, tracker=weak_tracker)
        result = graph.invoke(initial_state.model_dump())

        assert result["status"] == "closed"
        assert result["re_check_count"] == 1
        assert result["significant_findings"] is False

    def test_re_check_loop_max_iterations(self) -> None:
        """Even with significant findings, max 2 re-checks then forced to closer."""

        def weak_tracker(state: CaseState) -> dict[str, Any]:
            return {
                "tracker_confidence": Confidence.WEAK,
                "status": "shadowing",
                "hypotheses": [],
                "evidence_refs": [],
            }

        def significant_flanker(state: CaseState) -> dict[str, Any]:
            return {
                "flanker_confidence": Confidence.STRONG,
                "significant_findings": True,
                "re_check_count": state.re_check_count + 1,
            }

        seed = Seed(type="alert", raw_payload={})
        initial_state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.WEAK,
            re_check_count=0,
        )
        graph = build_hunt_graph(use_stubs=True, tracker=weak_tracker, flanker=significant_flanker)
        result = graph.invoke(initial_state.model_dump())

        assert result["status"] == "closed"
        # After 2 re-check iterations, the graph should terminate at closer
        assert result["re_check_count"] == 2

    def test_high_confidence_skips_flanker(self) -> None:
        """PLAUSIBLE (3) or higher should route directly to closer."""
        seed = Seed(type="alert", raw_payload={})
        initial_state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.PLAUSIBLE,
            re_check_count=0,
        )
        graph = build_hunt_graph(use_stubs=True)
        result = graph.invoke(initial_state.model_dump())

        assert result["status"] == "closed"
        # Flanker was never invoked, so re_check_count stays 0
        assert result["re_check_count"] == 0


class TestFlankerGraphNode:
    """Flanker as a graph node with custom implementations."""

    def test_custom_flanker_produces_branches(self) -> None:
        from wolfpack.schemas.branch import BranchSpec
        from wolfpack.schemas.hypothesis import Hypothesis

        def weak_tracker(state: CaseState) -> dict[str, Any]:
            return {
                "tracker_confidence": Confidence.WEAK,
                "status": "shadowing",
                "hypotheses": [],
                "evidence_refs": [],
            }

        def branching_flanker(state: CaseState) -> dict[str, Any]:
            return {
                "flanker_confidence": Confidence.STRONG,
                "significant_findings": False,
                "re_check_count": state.re_check_count + 1,
                "branches_to_create": [
                    BranchSpec(
                        hypothesis=Hypothesis(
                            description="DNS pivot branch",
                            confidence=Confidence.PLAUSIBLE,
                        ),
                        created_by="flanker",
                    )
                ],
            }

        seed = Seed(type="alert", raw_payload={})
        initial_state = CaseState(
            case_id=str(uuid.uuid4()),
            seed=seed,
            tracker_confidence=Confidence.WEAK,
            re_check_count=0,
        )
        graph = build_hunt_graph(use_stubs=True, tracker=weak_tracker, flanker=branching_flanker)
        result = graph.invoke(initial_state.model_dump())

        assert result["status"] == "closed"
        # Flanker was invoked (re_check_count incremented)
        assert result["re_check_count"] == 1
