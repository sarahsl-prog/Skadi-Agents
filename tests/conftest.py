"""Shared pytest fixtures for WolfPack tests."""

import os

import pytest

from wolfpack.config.settings import Settings

# Base env vars required by every Settings instance.
_BASE_ENV: dict[str, str] = {
    "DEPLOYMENT_MODE": "dev",
    "LLM__PROVIDER": "ollama",
    "LLM__BASE_URL": "http://localhost:11434",
    "LLM__MODEL": "llama3.2:1b",
    "POSTGRES__DSN": "postgresql://wolfpack:pass@localhost:5432/wolfpack",
}


@pytest.fixture()
def dev_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return Settings loaded with dev defaults (no external services required)."""
    for k, v in _BASE_ENV.items():
        monkeypatch.setenv(k, v)
    return Settings()


@pytest.fixture()
def airgapped_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Return Settings loaded for on_prem_airgapped with a private URL."""
    for k, v in {
        **_BASE_ENV,
        "DEPLOYMENT_MODE": "on_prem_airgapped",
        "LLM__BASE_URL": "http://192.168.1.10:11434",
    }.items():
        monkeypatch.setenv(k, v)
    return Settings()


@pytest.fixture()
def nats_url() -> str:
    """Return the NATS URL from env or a sensible default."""
    return os.environ.get("NATS__URL", "nats://localhost:4222")


@pytest.fixture()
def otel_endpoint() -> str:
    """Return the OTel OTLP HTTP endpoint from env or a sensible default."""
    return os.environ.get("OTEL__ENDPOINT", "http://localhost:4318")
