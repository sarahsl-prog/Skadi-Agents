"""Provider wrappers for pluggable LLM backends."""

from openai import AsyncOpenAI
from pydantic_ai.providers import Provider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider

from wolfpack.config.settings import LLMConfig


def build_ollama_provider(cfg: LLMConfig) -> Provider[AsyncOpenAI]:
    """Return an OllamaProvider configured from LLMConfig.

    Handles both local Ollama (base_url=http://localhost:11434) and
    Ollama Cloud (base_url=https://api.ollama.com, hosted=True).
    """
    import httpx

    http_client = httpx.AsyncClient(timeout=cfg.request_timeout_s)
    return OllamaProvider(
        base_url=cfg.base_url,
        api_key=cfg.api_key.get_secret_value() if cfg.api_key else None,
        http_client=http_client,
    )


def build_openai_compatible_provider(cfg: LLMConfig) -> Provider[AsyncOpenAI]:
    """Return an OpenAIProvider configured from LLMConfig.

    Covers vLLM, LM Studio, and any other OpenAI-compatible server.
    """
    import httpx

    http_client = httpx.AsyncClient(timeout=cfg.request_timeout_s)
    return OpenAIProvider(
        base_url=cfg.base_url,
        api_key=cfg.api_key.get_secret_value() if cfg.api_key else None,
        http_client=http_client,
    )
