"""Tests for Settings models and airgapped enforcement."""

import pytest
from pydantic import ValidationError

from wolfpack.config.deployment import DeploymentMode
from wolfpack.config.settings import Settings

# Base env vars required by every Settings instance.
# Tests override individual keys as needed.
_BASE: dict[str, str] = {
    "LLM__PROVIDER": "ollama",
    "LLM__BASE_URL": "http://localhost:11434",
    "LLM__MODEL": "llama3.2:1b",
    "POSTGRES__DSN": "postgresql://wolfpack:pass@localhost:5432/wolfpack",
}


def _load(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    """Apply env overrides then load Settings (reads live os.environ)."""
    for k, v in {**_BASE, **overrides}.items():
        monkeypatch.setenv(k, v)
    return Settings()


# ---------------------------------------------------------------------------
# Happy-path: all three deployment modes accept a local Ollama URL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    ["dev", "on_prem_connected", "on_prem_airgapped"],
)
def test_settings_loads_for_all_modes(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    settings = _load(monkeypatch, DEPLOYMENT_MODE=mode)
    assert settings.deployment_mode == DeploymentMode(mode)


def test_settings_private_url_accepted_in_airgapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _load(
        monkeypatch,
        DEPLOYMENT_MODE="on_prem_airgapped",
        LLM__BASE_URL="http://192.168.1.10:11434",
    )
    assert settings.deployment_mode is DeploymentMode.ON_PREM_AIRGAPPED


# ---------------------------------------------------------------------------
# Airgapped enforcement: public URL rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://api.ollama.com",
        "https://ollama.com",
        "http://8.8.8.8:11434",
    ],
)
def test_airgapped_rejects_public_base_url(monkeypatch: pytest.MonkeyPatch, bad_url: str) -> None:
    with pytest.raises(ValidationError, match="loopback or RFC-1918"):
        _load(
            monkeypatch,
            DEPLOYMENT_MODE="on_prem_airgapped",
            LLM__BASE_URL=bad_url,
        )


# ---------------------------------------------------------------------------
# Airgapped enforcement: hosted flag rejected
# ---------------------------------------------------------------------------


def test_airgapped_rejects_hosted_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="hosted"):
        _load(
            monkeypatch,
            DEPLOYMENT_MODE="on_prem_airgapped",
            LLM__HOSTED="true",
        )


# ---------------------------------------------------------------------------
# hosted flag is ignored outside airgapped mode
# ---------------------------------------------------------------------------


def test_hosted_flag_allowed_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(
        monkeypatch,
        DEPLOYMENT_MODE="dev",
        LLM__BASE_URL="https://api.ollama.com",
        LLM__HOSTED="true",
    )
    assert settings.llm.hosted is True


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_nats_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch, DEPLOYMENT_MODE="dev")
    assert settings.nats.url == "nats://localhost:4222"


def test_otel_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch, DEPLOYMENT_MODE="dev")
    assert settings.otel.endpoint == "http://localhost:4318"
    assert settings.otel.service_namespace == "wolfpack"


def test_mlflow_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch, DEPLOYMENT_MODE="dev")
    assert settings.mlflow.tracking_uri == "http://localhost:5000"


# ---------------------------------------------------------------------------
# SecretStr: DSN value is not exposed in repr
# ---------------------------------------------------------------------------


def test_postgres_dsn_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch, DEPLOYMENT_MODE="dev")
    assert "pass" not in repr(settings.postgres.dsn)
    assert "pass" in settings.postgres.dsn.get_secret_value()
