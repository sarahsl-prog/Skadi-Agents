"""Tests for the LLM factory and provider builders."""

import pytest
from pydantic import SecretStr
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from wolfpack.config.settings import LLMConfig
from wolfpack.llm.errors import LLMConfigError
from wolfpack.llm.factory import get_model
from wolfpack.llm.providers import build_ollama_provider, build_openai_compatible_provider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OLLAMA_CFG = LLMConfig(
    provider="ollama",
    base_url="http://localhost:11434",
    model="llama3.2:1b",
)

_OPENAI_COMPAT_CFG = LLMConfig(
    provider="openai_compatible",
    base_url="http://localhost:8000/v1",
    model="mistral-7b",
)


# ---------------------------------------------------------------------------
# Provider builders: correct provider type returned
# ---------------------------------------------------------------------------


def test_build_ollama_provider_returns_ollama_provider() -> None:
    provider = build_ollama_provider(_OLLAMA_CFG)
    assert isinstance(provider, OllamaProvider)


def test_build_openai_compatible_provider_returns_openai_provider() -> None:
    provider = build_openai_compatible_provider(_OPENAI_COMPAT_CFG)
    assert isinstance(provider, OpenAIProvider)


def test_build_ollama_provider_with_api_key() -> None:
    cfg = LLMConfig(
        provider="ollama",
        base_url="https://api.ollama.com",
        model="llama3.3:70b",
        api_key=SecretStr("tok-secret"),
        hosted=True,
    )
    # Should not raise; key is extracted from SecretStr inside the builder
    provider = build_ollama_provider(cfg)
    assert isinstance(provider, OllamaProvider)


def test_build_openai_compatible_provider_with_api_key() -> None:
    cfg = LLMConfig(
        provider="openai_compatible",
        base_url="http://my-vllm:8000/v1",
        model="mistral-7b",
        api_key=SecretStr("tok-vllm"),
    )
    provider = build_openai_compatible_provider(cfg)
    assert isinstance(provider, OpenAIProvider)


# ---------------------------------------------------------------------------
# Factory: returns OpenAIChatModel for supported providers (no network needed)
# ---------------------------------------------------------------------------


def test_get_model_ollama_returns_openai_model() -> None:
    model = get_model(_OLLAMA_CFG)
    assert isinstance(model, OpenAIChatModel)


def test_get_model_openai_compatible_returns_openai_model() -> None:
    model = get_model(_OPENAI_COMPAT_CFG)
    assert isinstance(model, OpenAIChatModel)


def test_get_model_never_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_model must work even when Ollama env vars are unset."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    model = get_model(_OLLAMA_CFG)
    assert isinstance(model, OpenAIChatModel)


# ---------------------------------------------------------------------------
# Factory: LLMConfigError on unsupported provider
# ---------------------------------------------------------------------------


def test_get_model_raises_llm_config_error_for_unknown_provider() -> None:
    # model_construct bypasses pydantic validation to inject an invalid provider
    cfg = LLMConfig.model_construct(
        provider="unsupported_provider",  # type: ignore[arg-type]  # intentional bypass
        base_url="http://localhost:11434",
        model="test",
        api_key=None,
        hosted=False,
        request_timeout_s=60.0,
    )
    with pytest.raises(LLMConfigError, match="unsupported provider"):
        get_model(cfg)


def test_llm_config_error_is_value_error() -> None:
    assert issubclass(LLMConfigError, ValueError)
