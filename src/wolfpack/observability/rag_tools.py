"""OpenTelemetry instrumentation for Haystack RAG retrieval calls.

Wraps pipeline ``retrieve()`` calls so every query produces a child span
with query metadata and latency.
"""

from __future__ import annotations

import hashlib
import inspect
import time
from typing import Any

from opentelemetry import trace

from wolfpack.observability.baggage import attach_baggage_to_span

TRACER = trace.get_tracer("wolfpack")


def traced_retrieve(pipeline_name: str, retrieve_fn: Any) -> Any:
    """Wrap a Haystack pipeline ``retrieve`` method with an OTel span.

    Returns a callable with the same signature as *retrieve_fn* that:

    - starts a span named ``rag.{pipeline_name}``
    - sets ``wolfpack.rag_pipeline``, ``wolfpack.query_hash``,
      ``wolfpack.top_k``, ``wolfpack.result_count``
    - records ``retrieval_latency_ms``
    - calls ``attach_baggage_to_span`` so the span carries case context
    """

    async def _async_wrapped(query: str, **kwargs: Any) -> Any:
        with TRACER.start_as_current_span(
            f"rag.{pipeline_name}",
            attributes={"wolfpack.rag_pipeline": pipeline_name},
        ) as span:
            attach_baggage_to_span(span)

            top_k = kwargs.get("top_k", 5)
            span.set_attribute("wolfpack.top_k", top_k)
            span.set_attribute(
                "wolfpack.query_hash",
                hashlib.sha256(query.encode()).hexdigest()[:16],
            )

            t0 = time.perf_counter()
            try:
                docs = await retrieve_fn(query, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise
            latency_ms = (time.perf_counter() - t0) * 1000

            span.set_attribute("wolfpack.result_count", len(docs))
            span.set_attribute("retrieval_latency_ms", latency_ms)
            return docs

    def _sync_wrapped(query: str, **kwargs: Any) -> Any:
        with TRACER.start_as_current_span(
            f"rag.{pipeline_name}",
            attributes={"wolfpack.rag_pipeline": pipeline_name},
        ) as span:
            attach_baggage_to_span(span)

            top_k = kwargs.get("top_k", 5)
            span.set_attribute("wolfpack.top_k", top_k)
            span.set_attribute(
                "wolfpack.query_hash",
                hashlib.sha256(query.encode()).hexdigest()[:16],
            )

            t0 = time.perf_counter()
            try:
                docs = retrieve_fn(query, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise
            latency_ms = (time.perf_counter() - t0) * 1000

            span.set_attribute("wolfpack.result_count", len(docs))
            span.set_attribute("retrieval_latency_ms", latency_ms)
            return docs

    if inspect.iscoroutinefunction(retrieve_fn):
        return _async_wrapped
    return _sync_wrapped
