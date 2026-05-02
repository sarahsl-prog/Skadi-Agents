"""Logfire wiring for WolfPack.

Configures Logfire to emit spans through the same OpenTelemetry pipeline
that the tracing module bootstraps.  This gives Pydantic AI agent runs
automatic Logfire instrumentation without a separate export path.
"""

import logfire
from opentelemetry import trace

from wolfpack.config.settings import Settings


def configure_logfire(settings: Settings) -> None:
    """Configure Logfire to use the OTel pipeline from bootstrap_tracing.

    Must be called *after* bootstrap_tracing so the global TracerProvider
    is already set.  Logfire will attach its spans to that provider.

    Raises:
        RuntimeError: If bootstrap_tracing() has not been called first.
    """
    provider = trace.get_tracer_provider()
    if not hasattr(provider, "resource"):
        raise RuntimeError(
            "bootstrap_tracing() must be called before configure_logfire()"
        )
    logfire.configure(
        service_name=settings.otel.service_name,
        send_to_logfire=False,  # we export through our own OTel collector
    )
