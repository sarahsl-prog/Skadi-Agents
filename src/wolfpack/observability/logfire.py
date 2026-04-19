"""Logfire wiring for WolfPack.

Configures Logfire to emit spans through the same OpenTelemetry pipeline
that the tracing module bootstraps.  This gives Pydantic AI agent runs
automatic Logfire instrumentation without a separate export path.
"""

import logfire

from wolfpack.config.settings import Settings


def configure_logfire(settings: Settings) -> None:
    """Configure Logfire to use the OTel pipeline from bootstrap_tracing.

    Must be called *after* bootstrap_tracing so the global TracerProvider
    is already set.  Logfire will attach its spans to that provider.
    """
    logfire.configure(
        service_name=settings.otel.service_name,
        send_to_logfire=False,  # we export through our own OTel collector
    )