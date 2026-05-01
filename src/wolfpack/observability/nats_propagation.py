"""NATS context propagation with OpenTelemetry.

Injects OTel trace context and baggage into NATS message headers so that
distributed traces span across the event bus.
"""

from __future__ import annotations

import json
from typing import Any

from opentelemetry import propagate
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()


def inject_nats_headers() -> dict[str, str]:
    """Return a dict of NATS message headers carrying the current OTel context."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    # JSON-encode baggage values for NATS header transport
    baggage = propagate.get_all()
    if baggage:
        carrier["wolfpack.baggage"] = json.dumps(baggage)
    return carrier


def extract_nats_headers(headers: dict[str, str] | None) -> None:
    """Restore OTel context from NATS message headers."""
    if headers is None:
        return
    _PROPAGATOR.extract(headers)
    raw_baggage = headers.get("wolfpack.baggage")
    if raw_baggage:
        try:
            baggage = json.loads(raw_baggage)
            for key, value in baggage.items():
                propagate.set_baggage(key, value)
        except json.JSONDecodeError:
            pass
