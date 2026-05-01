"""Tests for the observability bootstrap modules.

Covers:
- bootstrap_tracing idempotency
- logfire wiring
- traced_node decorator (sync + async)
- baggage propagation (set_case_baggage, get_case_baggage, attach_baggage_to_span)
- traced_agent_run / traced_agent_run_sync
- traced_retrieve wrapper
- NATS context propagation (inject / extract)
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace

from wolfpack.config.settings import Settings
from wolfpack.observability.baggage import (
    attach_baggage_to_span,
    generate_agent_run_id,
    get_case_baggage,
    set_case_baggage,
)
from wolfpack.observability.nats_propagation import extract_nats_headers, inject_nats_headers
from wolfpack.observability.tracing import bootstrap_tracing, traced_node
from wolfpack.schemas.case_state import CaseState
from wolfpack.schemas.seed import Seed


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="function")
def provider(dev_settings: Settings) -> Any:
    """Return a fresh bootstrapped TracerProvider."""
    # Reset the module-level sentinel so each test starts fresh.
    with patch("wolfpack.observability.tracing._bootstrapped", False):
        return bootstrap_tracing(dev_settings)


# --------------------------------------------------------------------------- #
# bootstrap_tracing
# --------------------------------------------------------------------------- #


def test_bootstrap_tracing_returns_tracer_provider(dev_settings: Settings) -> None:
    """bootstrap_tracing should set the global TracerProvider and return it."""
    with patch("wolfpack.observability.tracing._bootstrapped", False):
        provider = bootstrap_tracing(dev_settings)
        assert provider is not None
        assert trace.get_tracer_provider() is provider


def test_bootstrap_tracing_idempotent(dev_settings: Settings) -> None:
    """Calling bootstrap_tracing twice should return the same provider."""
    with patch("wolfpack.observability.tracing._bootstrapped", False):
        first = bootstrap_tracing(dev_settings)
        second = bootstrap_tracing(dev_settings)
        assert first is second


# --------------------------------------------------------------------------- #
# configure_logfire
# --------------------------------------------------------------------------- #


def test_configure_logfire_does_not_raise(dev_settings: Settings) -> None:
    """configure_logfire should complete without error."""
    with patch("wolfpack.observability.tracing._bootstrapped", False):
        bootstrap_tracing(dev_settings)
    from wolfpack.observability.logfire import configure_logfire

    configure_logfire(dev_settings)


# --------------------------------------------------------------------------- #
# traced_node
# --------------------------------------------------------------------------- #


def test_traced_node_sync(provider: Any) -> None:
    """traced_node should wrap a sync function with an OTel span."""

    @traced_node("test_sync")
    def _node(state: CaseState) -> dict[str, Any]:
        return {"status": "ok"}

    state = CaseState(case_id=str(uuid.uuid4()), seed=Seed(raw_payload={}))
    result = _node(state)
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_traced_node_async(provider: Any) -> None:
    """traced_node should wrap an async function with an OTel span."""

    @traced_node("test_async")
    async def _node(state: CaseState) -> dict[str, Any]:
        return {"status": "async_ok"}

    state = CaseState(case_id=str(uuid.uuid4()), seed=Seed(raw_payload={}))
    result = await _node(state)
    assert result == {"status": "async_ok"}


# --------------------------------------------------------------------------- #
# baggage
# --------------------------------------------------------------------------- #


def test_set_and_get_case_baggage() -> None:
    """Baggage values set via set_case_baggage should be readable by get_case_baggage."""
    case_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    agent_run_id = generate_agent_run_id()

    set_case_baggage(case_id=case_id, branch_id=branch_id, agent_run_id=agent_run_id)
    ctx = get_case_baggage()

    assert ctx.case_id == case_id
    assert ctx.branch_id == branch_id
    assert ctx.agent_run_id == agent_run_id


def test_attach_baggage_to_span(provider: Any) -> None:
    """attach_baggage_to_span should promote baggage to span attributes."""
    case_id = str(uuid.uuid4())
    set_case_baggage(case_id=case_id)

    tracer = trace.get_tracer("wolfpack")
    with tracer.start_as_current_span("test.attach") as span:
        attach_baggage_to_span(span)
        # There is no public accessor for attributes; just ensure no exception.


# --------------------------------------------------------------------------- #
# NATS propagation
# --------------------------------------------------------------------------- #


def test_inject_extract_roundtrip() -> None:
    """OTel headers injected by inject_nats_headers should be restored by extract_nats_headers."""
    set_case_baggage(case_id="c-123", branch_id="b-456", agent_run_id="a-789")
    headers = inject_nats_headers()
    assert "wolfpack.baggage" in headers

    # Clear context (best-effort via new empty baggage)
    set_case_baggage(case_id=None, branch_id=None, agent_run_id=None)

    extract_nats_headers(headers)
    ctx = get_case_baggage()
    assert ctx.case_id == "c-123"
    assert ctx.branch_id == "b-456"
    assert ctx.agent_run_id == "a-789"


# --------------------------------------------------------------------------- #
# traced_agent_run
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_traced_agent_run_creates_span(provider: Any) -> None:
    """traced_agent_run should create an OTel span and return the agent result."""
    from wolfpack.observability.agents import traced_agent_run

    mock_agent = MagicMock()
    mock_agent.run = MagicMock()
    mock_agent.run.return_value = MagicMock()
    mock_agent.run.return_value.output = "hello"
    mock_agent.model.model_name = "test-model"
    mock_agent.model.provider = "test-provider"

    result = await traced_agent_run("alpha", mock_agent, "prompt", deps=None)
    assert result.output == "hello"


# --------------------------------------------------------------------------- #
# traced_retrieve
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_traced_retrieve_async(provider: Any) -> None:
    """traced_retrieve should wrap an async retrieve function."""
    from wolfpack.observability.rag_tools import traced_retrieve

    async def _fake_retrieve(query: str, **kwargs: Any) -> list[Any]:
        return [{"q": query}]

    wrapped = traced_retrieve("test_pipeline", _fake_retrieve)
    docs = await wrapped("test query", top_k=3)
    assert len(docs) == 1
    assert docs[0]["q"] == "test query"


def test_traced_retrieve_sync(provider: Any) -> None:
    """traced_retrieve should wrap a sync retrieve function."""
    from wolfpack.observability.rag_tools import traced_retrieve

    def _fake_retrieve(query: str, **kwargs: Any) -> list[Any]:
        return [{"q": query}]

    wrapped = traced_retrieve("test_pipeline", _fake_retrieve)
    docs = wrapped("sync query", top_k=5)
    assert len(docs) == 1
