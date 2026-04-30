"""Unit tests for Tracker agent and confidence calibration."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from wolfpack.agents.tracker import (
    TRACKER_TOOL_ALLOWLIST,
    TrackerDeps,
    _validate_tools,
    run_tracker,
)
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence, calibrate
from wolfpack.schemas.seed import Seed


class TestToolAllowlist:
    """Tracker tool allowlist enforcement."""

    def test_allowed_tools_pass(self) -> None:
        def threat_intel_tool() -> None:
            pass

        def case_history_tool() -> None:
            pass

        _validate_tools([threat_intel_tool, case_history_tool])

    def test_disallowed_tool_raises(self) -> None:
        def rogue_tool() -> None:
            pass

        with pytest.raises(RuntimeError, match="rogue_tool"):
            _validate_tools([rogue_tool])

    def test_allowlist_contains_expected_tools(self) -> None:
        assert "threat_intel_tool" in TRACKER_TOOL_ALLOWLIST
        assert "case_history_tool" in TRACKER_TOOL_ALLOWLIST
        assert "syslog_query" in TRACKER_TOOL_ALLOWLIST
        assert "crowdstrike_query" in TRACKER_TOOL_ALLOWLIST


class TestConfidenceCalibration:
    """Confidence calibration helper."""

    def test_no_evidence_downgrades(self) -> None:
        result = calibrate(Confidence.PLAUSIBLE, 0, "none")
        assert result <= Confidence.PLAUSIBLE

    def test_high_evidence_independent_boosts(self) -> None:
        result = calibrate(Confidence.WEAK, 5, "independent")
        assert result >= Confidence.STRONG

    def test_multiple_corroboration_boosts(self) -> None:
        result = calibrate(Confidence.COINCIDENCE, 3, "multiple")
        assert result > Confidence.COINCIDENCE

    def test_cap_at_high_fidelity(self) -> None:
        result = calibrate(Confidence.STRONG, 10, "independent")
        assert result == Confidence.HIGH_FIDELITY

    def test_floor_at_coincidence(self) -> None:
        result = calibrate(Confidence.COINCIDENCE, 0, "none")
        assert result == Confidence.COINCIDENCE


class TestRunTracker:
    """Tracker agent execution with mocked LLM."""

    @pytest.mark.asyncio
    async def test_run_tracker_produces_output(self) -> None:
        seed = Seed(
            type="ioc",
            raw_payload={"entities": [{"type": "ip", "value": "10.0.0.1"}]},
        )
        state = CaseState(
            case_id="test-case-1",
            seed=seed,
        )

        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))

        assert "tracker_confidence" in result
        assert "status" in result
        assert result["status"] == "shadowing"

    @pytest.mark.asyncio
    async def test_run_tracker_with_no_entities(self) -> None:
        seed = Seed(type="hunt_query", raw_payload={})
        state = CaseState(
            case_id="test-case-2",
            seed=seed,
        )

        deps = TrackerDeps()
        result = await run_tracker(state, deps=deps, model=TestModel(call_tools=[]))

        assert result["status"] == "shadowing"
        assert result["tracker_confidence"] is not None
