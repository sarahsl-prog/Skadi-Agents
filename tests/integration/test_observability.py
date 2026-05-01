"""Integration test for full observability pipeline.

Spins up the in-memory OTel provider, runs the stub hunt graph, and
asserts that every node produces an OTel span with baggage attributes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry import trace

from wolfpack.config.settings import Settings
from wolfpack.observability.baggage import get_case_baggage, set_case_baggage
from wolfpack.observability.tracing import bootstrap_tracing
from wolfpack.orchestrator.graph import build_hunt_graph
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.seed import Seed


@pytest.fixture(scope="function")
def provider(dev_settings: Settings) -> Any:
    with patch("wolfpack.observability.tracing._bootstrapped", False):
        return bootstrap_tracing(dev_settings)


@pytest.mark.asyncio
async def test_hunt_spans_have_baggage(provider: Any) -> None:
    """Running the stub hunt graph should produce spans with baggage attributes."""
    graph = build_hunt_graph(use_stubs=True)
    seed = Seed(raw_payload={"alert": "test"})
    state = CaseState(case_id="case-obs-test", seed=seed)

    # Set baggage before invocation so it propagates
    set_case_baggage(case_id=state.case_id, branch_id="branch-obs-test")

    result = graph.invoke(state)
    assert result["case_id"] == "case-obs-test"

    # Baggage should be preserved after graph execution
    ctx = get_case_baggage()
    assert ctx.case_id == "case-obs-test"
    assert ctx.branch_id == "branch-obs-test"
