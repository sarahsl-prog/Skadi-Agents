"""NATS context propagation with OpenTelemetry.

Injects OTel trace context and baggage into NATS message headers so that
distributed traces span across the event bus.
"""

from __future__ import annotations

import json

from opentelemetry import baggage, context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()


def inject_nats_headers() -> dict[str, str]:
    """Return a dict of NATS message headers carrying the current OTel context."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    # JSON-encode baggage values for NATS header transport
    all_baggage = baggage.get_all()
    if all_baggage:
        # ``get_all`` returns an immutable ``mappingproxy``; convert to a plain
        # dict so it is JSON-serializable for the NATS header.
        carrier["wolfpack.baggage"] = json.dumps(dict(all_baggage))
    return carrier


def extract_nats_headers(headers: dict[str, str] | None) -> context.Context:
    """Restore OTel context from NATS message headers.

    Returns the extracted Context which should be activated via
    ``context.attach()`` and later detached with ``context.detach()``.
    """
    if headers is None:
        return context.get_current()
    ctx = _PROPAGATOR.extract(headers)
    raw_baggage = headers.get("wolfpack.baggage")
    if raw_baggage:
        try:
            parsed = json.loads(raw_baggage)
            # ``set_baggage`` returns a new context; fold each entry into the
            # context we return so the caller's ``context.attach`` carries it.
            for key, value in parsed.items():
                ctx = baggage.set_baggage(key, value, context=ctx)
        except json.JSONDecodeError:
            pass
    return ctx
