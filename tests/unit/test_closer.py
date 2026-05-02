"""Unit tests for the Closer agent."""

from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from wolfpack.adapters.base import Event, TelemetrySource, TimeWindow
from wolfpack.adapters.tools import telemetry_tool_factory
from wolfpack.agents.closer import CLOSER_TOOL_ALLOWLIST, _build_closer_agent, run_closer
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.confidence import Confidence
from wolfpack.schemas.entity import Entity
from wolfpack.schemas.evidence import EvidenceRef
from wolfpack.schemas.hypothesis import Hypothesis
from wolfpack.schemas.seed import Seed


class _FakeAdapter(TelemetrySource):
    name = "fake_tool"

    async def query(
        self,
        entity: Entity,
        time_window: TimeWindow,
        filters: dict[str, Any] | None = None,
    ) -> list[Event]:
        return []

    async def health_check(self) -> bool:
        return True


@pytest.mark.anyio
async def test_closer_produces_verdict_packet() -> None:
    """Closer returns a structured verdict packet."""
    state = CaseState(
        case_id="test-closer-1",
        seed=Seed(
            type="ioc",
            raw_payload={"entities": [{"type": "ip", "value": "192.0.2.1"}]},
        ),
        hypotheses=[
            Hypothesis(description="Test hypothesis", confidence=Confidence.PLAUSIBLE)
        ],
        evidence_refs=[EvidenceRef(source_type="stub", source_id="ev-001")],
    )

    result = await run_closer(state, model=TestModel())
    assert "verdict_decision" in result
    assert result["status"] == "review"
    assert "verdict_packet" in result
    packet = result["verdict_packet"]
    assert "decision" in packet
    assert packet["confidence"] is not None


def test_tool_allowlist_blocks_unknown_tools() -> None:
    """Unknown tools are not added to the Closer agent."""
    tool = telemetry_tool_factory(_FakeAdapter())
    # Ensure fake tool is NOT in closer allowlist
    assert tool.__name__ not in CLOSER_TOOL_ALLOWLIST


def test_build_closer_agent_with_mock_model() -> None:
    """The factory returns an Agent when given a mock model."""
    agent = _build_closer_agent(model=TestModel())
    assert agent is not None
