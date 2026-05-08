"""Edge-case unit tests for Alpha, Tracker, and Closer agents.

Covers boundary conditions: empty inputs, extreme entity counts,
malformed payloads, and oversized data.

All tests use :class:`pydantic_ai.models.test.TestModel` so no real LLM
is invoked.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from wolfpack.agents.alpha import AlphaDispatcher
from wolfpack.agents.closer import CLOSER_TOOL_ALLOWLIST, _build_closer_agent, run_closer
from wolfpack.agents.tracker import TrackerDeps, run_tracker
from wolfpack.schemas.agents.alpha import AlphaOutput
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence, calibrate
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


# --------------------------------------------------------------------------- #
# Alpha Dispatcher edge cases
# --------------------------------------------------------------------------- #


class TestAlphaEdgeCases:
    """Boundary tests for AlphaDispatcher."""

    @pytest.mark.asyncio
    async def test_empty_seed_payload(self) -> None:
        """Alpha must handle a seed with an empty raw_payload."""
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "alpha-empty",
                    "seed": {"type": "alert", "raw_payload": {}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "",
            }
        )
        dispatcher = AlphaDispatcher(model=model)
        seed = Seed(type="alert", raw_payload={})
        result = await dispatcher.dispatch(seed)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.case_id == "alpha-empty"
        assert result.next_agent == "tracker"

    @pytest.mark.asyncio
    async def test_very_large_seed_payload(self) -> None:
        """Alpha must accept a seed with a large (10 KB) raw_payload."""
        large_value = "A" * 10_000
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "alpha-large",
                    "seed": {"type": "hunt_query", "raw_payload": {"query": large_value}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "Large payload test",
            }
        )
        dispatcher = AlphaDispatcher(model=model)
        seed = Seed(type="hunt_query", raw_payload={"query": large_value})
        result = await dispatcher.dispatch(seed)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.case_id == "alpha-large"

    def test_dispatch_sync_with_none_pool(self) -> None:
        """Synchronous dispatch must work when pool is None."""
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "alpha-sync-none",
                    "seed": {"type": "ioc", "raw_payload": {"value": "8.8.8.8"}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "",
            }
        )
        dispatcher = AlphaDispatcher(model=model)
        seed = Seed(type="ioc", raw_payload={"value": "8.8.8.8"})
        result = dispatcher.dispatch_sync(seed, pool=None)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.status == "scented"

    @pytest.mark.asyncio
    async def test_unicode_in_seed_payload(self) -> None:
        """Alpha must handle unicode characters in the seed payload."""
        model = TestModel(
            custom_output_args={
                "case_state": {
                    "case_id": "alpha-unicode",
                    "seed": {"type": "hunt_query", "raw_payload": {"value": "测试"}},
                    "status": "scented",
                    "branches": [],
                    "hypotheses": [],
                    "evidence_refs": [],
                },
                "next_agent": "tracker",
                "task_description": "Unicode test",
            }
        )
        dispatcher = AlphaDispatcher(model=model)
        seed = Seed(type="hunt_query", raw_payload={"value": "测试"})
        result = await dispatcher.dispatch(seed)
        assert isinstance(result, AlphaOutput)
        assert result.case_state.case_id == "alpha-unicode"


# --------------------------------------------------------------------------- #
# Tracker edge cases
# --------------------------------------------------------------------------- #


class TestTrackerEdgeCases:
    """Boundary tests for Tracker agent."""

    @pytest.mark.asyncio
    async def test_zero_entities(self) -> None:
        """Tracker must not fail when the entity list is empty."""
        seed = Seed(type="hunt_query", raw_payload={})
        state = CaseState(case_id="tracker-zero", seed=seed)
        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))
        assert result["status"] == "shadowing"
        assert "tracker_confidence" in result

    @pytest.mark.asyncio
    async def test_single_entity(self) -> None:
        """Tracker must handle a single entity gracefully."""
        seed = Seed(
            type="ioc",
            raw_payload={"entities": [{"type": "ip", "value": "10.0.0.1"}]},
        )
        state = CaseState(case_id="tracker-one", seed=seed)
        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))
        assert result["status"] == "shadowing"

    @pytest.mark.asyncio
    async def test_many_entities(self) -> None:
        """Tracker must handle 150 entities without truncation errors."""
        entities = [{"type": "ip", "value": f"10.0.0.{i}"} for i in range(1, 151)]
        seed = Seed(type="ioc", raw_payload={"entities": entities})
        state = CaseState(case_id="tracker-many", seed=seed)
        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))
        assert result["status"] == "shadowing"
        assert "tracker_confidence" in result

    @pytest.mark.asyncio
    async def test_mixed_entity_types(self) -> None:
        """Tracker must handle a mix of entity types."""
        entities = [
            {"type": "ip", "value": "10.0.0.1"},
            {"type": "domain", "value": "evil.com"},
            {"type": "hash", "value": "d41d8cd98f00b204e9800998ecf8427e"},
            {"type": "user", "value": "admin"},
            {"type": "host", "value": "WIN-DESKTOP-01"},
            {"type": "url", "value": "http://evil.com/payload"},
        ]
        seed = Seed(type="ioc", raw_payload={"entities": entities})
        state = CaseState(case_id="tracker-mixed", seed=seed)
        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))
        assert result["status"] == "shadowing"

    @pytest.mark.asyncio
    async def test_unicode_entity_values(self) -> None:
        """Tracker must handle unicode entity values."""
        seed = Seed(
            type="ioc",
            raw_payload={"entities": [{"type": "domain", "value": "测试域名.com"}]},
        )
        state = CaseState(case_id="tracker-unicode", seed=seed)
        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))
        assert result["status"] == "shadowing"


# --------------------------------------------------------------------------- #
# Closer edge cases
# --------------------------------------------------------------------------- #


class TestCloserEdgeCases:
    """Boundary tests for Closer agent."""

    @pytest.mark.anyio
    async def test_zero_hypotheses(self) -> None:
        """Closer must handle a case with no hypotheses."""
        state = CaseState(
            case_id="closer-zero-hypotheses",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=[],
            evidence_refs=[],
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"
        assert "verdict_packet" in result
        packet = result["verdict_packet"]
        assert packet["decision"] is not None

    @pytest.mark.anyio
    async def test_zero_evidence(self) -> None:
        """Closer must handle a case with no evidence."""
        state = CaseState(
            case_id="closer-zero-evidence",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=[
                Hypothesis(description="Test hypothesis", confidence=Confidence.PLAUSIBLE)
            ],
            evidence_refs=[],
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"
        assert "verdict_packet" in result

    @pytest.mark.anyio
    async def test_many_hypotheses(self) -> None:
        """Closer must handle 100 hypotheses."""
        hypotheses = [
            Hypothesis(description=f"Hypothesis {i}", confidence=Confidence.WEAK)
            for i in range(100)
        ]
        state = CaseState(
            case_id="closer-many-hypotheses",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=hypotheses,
            evidence_refs=[],
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"

    @pytest.mark.anyio
    async def test_many_evidence_refs(self) -> None:
        """Closer must handle 100 evidence references."""
        evidence = [
            EvidenceRef(source_type="stub", source_id=f"ev-{i:03d}")
            for i in range(100)
        ]
        state = CaseState(
            case_id="closer-many-evidence",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=[
                Hypothesis(description="Test hypothesis", confidence=Confidence.STRONG)
            ],
            evidence_refs=evidence,
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"

    @pytest.mark.anyio
    async def test_high_confidence_verdict(self) -> None:
        """Closer must preserve high-confidence verdicts."""
        state = CaseState(
            case_id="closer-high-confidence",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=[
                Hypothesis(description="Strong hypothesis", confidence=Confidence.HIGH_FIDELITY)
            ],
            evidence_refs=[
                EvidenceRef(source_type="telemetry", source_id="ev-001")
            ],
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"
        packet = result["verdict_packet"]
        assert packet["confidence"] is not None

    @pytest.mark.anyio
    async def test_unicode_hypothesis_description(self) -> None:
        """Closer must handle unicode in hypothesis descriptions."""
        state = CaseState(
            case_id="closer-unicode",
            seed=Seed(type="ioc", raw_payload={"value": "10.0.0.1"}),
            hypotheses=[
                Hypothesis(description="测试描述", confidence=Confidence.PLAUSIBLE)
            ],
            evidence_refs=[],
        )
        result = await run_closer(state, model=TestModel(call_tools=[]))
        assert result["status"] == "review"


# --------------------------------------------------------------------------- #
# Confidence calibration edge cases
# --------------------------------------------------------------------------- #


class TestConfidenceCalibrationEdgeCases:
    """Boundary tests for confidence calibration."""

    def test_negative_evidence_count(self) -> None:
        """Calibration must not break with negative evidence counts."""
        result = calibrate(Confidence.PLAUSIBLE, -5, "none")
        assert isinstance(result, Confidence)
        assert result >= Confidence.COINCIDENCE

    def test_very_high_evidence_count(self) -> None:
        """Calibration must cap at HIGH_FIDELITY regardless of evidence count."""
        result = calibrate(Confidence.WEAK, 1_000_000, "independent")
        assert result == Confidence.HIGH_FIDELITY

    def test_unknown_corroboration_level(self) -> None:
        """Calibration must degrade gracefully with unknown corroboration levels."""
        result = calibrate(Confidence.STRONG, 5, "unknown_level")
        assert isinstance(result, Confidence)
        assert result >= Confidence.COINCIDENCE

    def test_calibrate_from_coincidence_with_no_evidence(self) -> None:
        """Coincidence + 0 evidence should remain Coincidence."""
        result = calibrate(Confidence.COINCIDENCE, 0, "none")
        assert result == Confidence.COINCIDENCE
