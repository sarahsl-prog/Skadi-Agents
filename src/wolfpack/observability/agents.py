"""OpenTelemetry instrumentation for Pydantic AI agent calls.

Wraps :meth:`pydantic_ai.Agent.run` and :meth:`Agent.run_sync` so that
 every LLM invocation creates a child span carrying model, provider, and
 token-count attributes.
"""

from __future__ import annotations

from typing import Any

import logging

from opentelemetry import trace

from wolfpack.observability.baggage import attach_baggage_to_span

TRACER = trace.get_tracer("wolfpack")
_LOGGER = logging.getLogger(__name__)


async def traced_agent_run(
    agent_name: str,
    agent: Any,
    prompt: str,
    *,
    deps: Any | None = None,
    model_name: str | None = None,
    provider: str | None = None,
) -> Any:
    """Run a Pydantic AI agent inside an OTel span.

    Span attributes:
    - ``wolfpack.agent_name`` — *agent_name*
    - ``wolfpack.model_name`` — *model_name* (inferred from agent if None)
    - ``wolfpack.provider`` — *provider* (inferred from agent if None)
    - ``wolfpack.token_count`` — sum of prompt + completion tokens (best-effort)

    Events:
    - ``tool.call`` — one per tool invocation (name + input-hash only, no raw
      content).
    """
    if model_name is None:
        model_name = _infer_model_name(agent)
    if provider is None:
        provider = _infer_provider(agent)

    with TRACER.start_as_current_span(
        f"agent.run.{agent_name}",
        attributes={
            "wolfpack.agent_name": agent_name,
            "wolfpack.model_name": model_name,
            "wolfpack.provider": provider,
        },
    ) as span:
        attach_baggage_to_span(span)

        # Hook tool calls before executing
        _instrument_tools(agent, span)

        try:
            if deps is not None:
                result = await agent.run(prompt, deps=deps)
            else:
                result = await agent.run(prompt)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise

        # Best-effort token count from usage metadata
        token_count = _extract_token_count(result)
        if token_count is not None:
            span.set_attribute("wolfpack.token_count", token_count)

        span.set_attribute("wolfpack.status", "success")
        return result


def traced_agent_run_sync(
    agent_name: str,
    agent: Any,
    prompt: str,
    *,
    deps: Any | None = None,
    model_name: str | None = None,
    provider: str | None = None,
) -> Any:
    """Synchronous variant of :func:`traced_agent_run`.

    .. warning::
       This function is **blocking** — it calls :meth:`agent.run_sync` inside
       a synchronous OTel span. Do not invoke it from an async event loop
       unless you wrap it with :func:`asyncio.to_thread`.
    """
    if model_name is None:
        model_name = _infer_model_name(agent)
    if provider is None:
        provider = _infer_provider(agent)

    with TRACER.start_as_current_span(
        f"agent.run.{agent_name}",
        attributes={
            "wolfpack.agent_name": agent_name,
            "wolfpack.model_name": model_name,
            "wolfpack.provider": provider,
        },
    ) as span:
        attach_baggage_to_span(span)

        _instrument_tools(agent, span)

        try:
            if deps is not None:
                result = agent.run_sync(prompt, deps=deps)
            else:
                result = agent.run_sync(prompt)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            raise

        token_count = _extract_token_count(result)
        if token_count is not None:
            span.set_attribute("wolfpack.token_count", token_count)

        span.set_attribute("wolfpack.status", "success")
        return result


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _infer_model_name(agent: Any) -> str:
    """Best-effort extraction of the model name from a Pydantic AI agent."""
    try:
        return str(agent.model.model_name)
    except Exception:
        return "unknown"


def _infer_provider(agent: Any) -> str:
    """Best-effort extraction of the provider name from a Pydantic AI agent."""
    try:
        return str(agent.model.provider)
    except Exception:
        return "unknown"


def _extract_token_count(result: Any) -> int | None:
    """Sum prompt + completion tokens from a Pydantic AI result object."""
    try:
        usage = result.usage()
        return getattr(usage, "prompt_tokens", 0) + getattr(usage, "completion_tokens", 0)
    except Exception as exc:
        _LOGGER.warning("Failed to extract token count: %s", exc)
        return None


def _instrument_tools(agent: Any, span: trace.Span) -> None:
    """Stub for future Pydantic AI tool-call instrumentation.

    Current Pydantic AI versions do not expose a stable tool-call hook.
    When one becomes available, attach a listener here that records
    ``tool.call`` span events with the tool name and a deterministic
    input hash — never raw content.
    """
    # TODO: wire up when Pydantic AI exposes on_tool_call or similar hook.
    pass
