"""Phase 0 smoke test — traced LLM call against the local stack.

Usage:  uv run python -m wolfpack.smoke.hello_pack

Loads settings, bootstraps tracing, builds the model, and runs a trivial
Pydantic AI request.  Prints the trace ID and destination for inspection.
"""

from __future__ import annotations

import typer
from opentelemetry import trace

from wolfpack.config.settings import Settings
from wolfpack.llm.factory import get_model
from wolfpack.observability.logfire import configure_logfire
from wolfpack.observability.tracing import bootstrap_tracing

app = typer.Typer(add_completion=False)


@app.command()
def smoke() -> None:
    """Run the Phase 0 smoke test against the local compose stack."""
    settings = Settings()

    # Wire observability before any LLM call.
    bootstrap_tracing(settings)
    configure_logfire(settings)

    model = get_model(settings.llm)
    tracer = trace.get_tracer("wolfpack.smoke")

    with tracer.start_as_current_span("smoke.hello_pack") as span:
        span.set_attribute("llm.provider", settings.llm.provider)
        span.set_attribute("llm.model", settings.llm.model)

        # Use the pydantic-ai agent interface for a minimal traced request.
        from pydantic_ai import Agent

        agent = Agent(model=model, system_prompt="You are a brief assistant.")
        result = agent.run_sync("Say 'Hello, WolfPack!' and nothing else.")

        span.set_attribute("smoke.output", result.output)
        span_context = span.get_span_context()

        typer.echo(f"Trace ID : {format(span_context.trace_id, '032x')}")
        typer.echo(f"Span ID  : {format(span_context.span_id, '016x')}")
        typer.echo(f"OTel     : {settings.otel.endpoint}")
        typer.echo(f"Response : {result.output}")


if __name__ == "__main__":
    app()
