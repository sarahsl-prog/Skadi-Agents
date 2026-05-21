"""Unit tests for the Analyst Console API token auth."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from wolfpack.api.auth import _verify_token

_BASE_ENV = {
    "DEPLOYMENT_MODE": "dev",
    "LLM__PROVIDER": "ollama",
    "LLM__BASE_URL": "http://localhost:11434",
    "LLM__MODEL": "llama3.2",
    "POSTGRES__DSN": "postgresql://u:p@localhost:5432/db",
}

_DEV_DEFAULT = "dev-token-do-not-use-in-production"


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for k, v in {**_BASE_ENV, **overrides}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("WOLFPACK_API_TOKEN", raising=False)


async def test_dev_default_token_accepted(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    assert await _verify_token(_DEV_DEFAULT) == _DEV_DEFAULT


async def test_dev_wrong_token_rejected(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await _verify_token("wrong")
    assert exc.value.status_code == 401


async def test_missing_token_rejected(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await _verify_token(None)
    assert exc.value.status_code == 401


async def test_non_dev_requires_env_token(monkeypatch: Any) -> None:
    # Without WOLFPACK_API_TOKEN, non-dev deployments must fail closed.
    _set_env(monkeypatch, DEPLOYMENT_MODE="on_prem_connected")
    with pytest.raises(HTTPException) as exc:
        await _verify_token("anything")
    assert exc.value.status_code == 401
    assert "WOLFPACK_API_TOKEN" in exc.value.detail


async def test_explicit_token_accepted_and_enforced(monkeypatch: Any) -> None:
    _set_env(monkeypatch, DEPLOYMENT_MODE="on_prem_connected")
    monkeypatch.setenv("WOLFPACK_API_TOKEN", "s3cret-token")
    assert await _verify_token("s3cret-token") == "s3cret-token"
    with pytest.raises(HTTPException):
        await _verify_token("not-the-token")


async def test_dev_default_not_accepted_when_env_token_set(monkeypatch: Any) -> None:
    # If an explicit token is configured, the dev default must not work.
    _set_env(monkeypatch)
    monkeypatch.setenv("WOLFPACK_API_TOKEN", "real-token")
    with pytest.raises(HTTPException):
        await _verify_token(_DEV_DEFAULT)
