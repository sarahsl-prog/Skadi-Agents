"""OpenTelemetry baggage propagation for WolfPack.

Provides helpers to attach `case_id`, `branch_id`, and `agent_run_id`
to the current OTel context so that every child span — LLM calls, tool
calls, NATS messages, ledger writes — carries the full operational
context automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from opentelemetry import context as otel_context
from opentelemetry.baggage import get_baggage, set_baggage
from opentelemetry.trace import Span


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class CaseBaggage:
    """Operational context propagated through OTel baggage."""

    case_id: str | None = None
    branch_id: str | None = None
    agent_run_id: str | None = None


def set_case_baggage(
    *,
    case_id: str | None = None,
    branch_id: str | None = None,
    agent_run_id: str | None = None,
) -> CaseBaggage:
    """Set the case context on OTel baggage.

    Returns the :class:`CaseBaggage` snapshot that was written.
    """
    snapshot = CaseBaggage(
        case_id=case_id,
        branch_id=branch_id,
        agent_run_id=agent_run_id,
    )
    # ``set_baggage`` returns a *new* immutable context rather than mutating
    # the active one. Chain the writes through ``context=`` and attach the
    # result so subsequent ``get_case_baggage`` calls in this execution see it.
    ctx = otel_context.get_current()
    if case_id is not None:
        ctx = set_baggage("wolfpack.case_id", case_id, context=ctx)
    if branch_id is not None:
        ctx = set_baggage("wolfpack.branch_id", branch_id, context=ctx)
    if agent_run_id is not None:
        ctx = set_baggage("wolfpack.agent_run_id", agent_run_id, context=ctx)
    otel_context.attach(ctx)
    return snapshot


def get_case_baggage() -> CaseBaggage:
    """Read the current case context from OTel baggage."""
    return CaseBaggage(
        case_id=_as_str(get_baggage("wolfpack.case_id")),
        branch_id=_as_str(get_baggage("wolfpack.branch_id")),
        agent_run_id=_as_str(get_baggage("wolfpack.agent_run_id")),
    )


def generate_agent_run_id() -> str:
    """Return a fresh UUID for a graph execution."""
    return str(uuid.uuid4())


def attach_baggage_to_span(span: Span) -> None:
    """Promote OTel baggage values to span attributes.

    Call this inside every LangGraph node span so that the span
    attributes match the current baggage context.
    """
    ctx = get_case_baggage()
    if ctx.case_id:
        span.set_attribute("wolfpack.case_id", ctx.case_id)
    if ctx.branch_id:
        span.set_attribute("wolfpack.branch_id", ctx.branch_id)
    if ctx.agent_run_id:
        span.set_attribute("wolfpack.agent_run_id", ctx.agent_run_id)
