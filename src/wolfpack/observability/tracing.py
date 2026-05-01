"""OpenTelemetry bootstrap helpers.

Initialises a global TracerProvider with resource attributes and an OTLP exporter
driven by the application Settings.  Safe to call multiple times — subsequent
calls after the first are no-ops.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Awaitable, Callable

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from wolfpack.config.settings import Settings
from wolfpack.observability.baggage import attach_baggage_to_span

_bootstrapped = False

TRACER_NAME = "wolfpack"


def bootstrap_tracing(settings: Settings) -> TracerProvider:
    """Initialise the global TracerProvider from Settings.

    Sets resource attributes (service.name, service.namespace,
    deployment.environment) and wires an OTLP HTTP exporter pointed at
    settings.otel.endpoint.  The global provider is set on first call only.
    """
    global _bootstrapped
    if _bootstrapped:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    resource = Resource.create(
        {
            "service.name": settings.otel.service_name,
            "service.namespace": settings.otel.service_namespace,
            "deployment.environment": settings.deployment_mode.value,
        }
    )

    exporter = OTLPSpanExporter(endpoint=f"{settings.otel.endpoint}/v1/traces")
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _bootstrapped = True
    return provider


# --------------------------------------------------------------------------- #
# LangGraph node instrumentation
# --------------------------------------------------------------------------- #

NodeFn = (
    Callable[[Any], dict[str, Any]]
    | Callable[[Any], Awaitable[dict[str, Any]]]
)


def traced_node(
    agent_name: str,
    node_fn: NodeFn | None = None,
) -> NodeFn:
    """Wrap a LangGraph node handler with an OTel span.

    Usage as a decorator::

        @traced_node("tracker")
        def tracker_node(state):
            ...

    Usage with async handlers::

        @traced_node("closer")
        async def closer_node(state):
            ...
    """

    def _outer_wrapper(fn: NodeFn) -> NodeFn:
        tracer = trace.get_tracer(TRACER_NAME)

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def _async_wrapped(state: Any) -> dict[str, Any]:
                with tracer.start_as_current_span(
                    f"node.{agent_name}",
                    attributes={"wolfpack.agent_name": agent_name},
                ) as span:
                    attach_baggage_to_span(span)
                    try:
                        result = await fn(state)
                        span.set_attribute("wolfpack.status", result.get("status", "unknown"))
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(trace.StatusCode.ERROR, str(exc))
                        raise

            return _async_wrapped

        @functools.wraps(fn)
        def _sync_wrapped(state: Any) -> dict[str, Any]:
            with tracer.start_as_current_span(
                f"node.{agent_name}",
                attributes={"wolfpack.agent_name": agent_name},
            ) as span:
                attach_baggage_to_span(span)
                try:
                    result = fn(state)
                    span.set_attribute("wolfpack.status", result.get("status", "unknown"))
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    raise

        return _sync_wrapped

    if node_fn is not None:
        return _outer_wrapper(node_fn)
    return _outer_wrapper
