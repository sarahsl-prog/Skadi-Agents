"""Tests for the observability bootstrap modules."""

from opentelemetry import trace

from wolfpack.config.settings import Settings
from wolfpack.observability.tracing import bootstrap_tracing


def test_bootstrap_tracing_returns_tracer_provider(dev_settings: Settings) -> None:
    """bootstrap_tracing should set the global TracerProvider and return it."""
    provider = bootstrap_tracing(dev_settings)
    assert provider is not None

    # Global provider should now be our provider.
    global_provider = trace.get_tracer_provider()
    assert global_provider is provider


def test_bootstrap_tracing_idempotent(dev_settings: Settings) -> None:
    """Calling bootstrap_tracing twice should return the same provider."""
    first = bootstrap_tracing(dev_settings)
    second = bootstrap_tracing(dev_settings)
    assert first is second


def test_configure_logfire_does_not_raise(dev_settings: Settings) -> None:
    """configure_logfire should complete without error."""
    # Ensure tracing is bootstrapped first (Logfire depends on it).
    bootstrap_tracing(dev_settings)

    from wolfpack.observability.logfire import configure_logfire

    configure_logfire(dev_settings)
