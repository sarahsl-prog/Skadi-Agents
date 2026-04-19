"""Model factory entry points."""

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel

from wolfpack.config.settings import LLMConfig
from wolfpack.llm.errors import LLMConfigError
from wolfpack.llm.providers import build_ollama_provider, build_openai_compatible_provider


def get_model(cfg: LLMConfig) -> Model:
    """Return a Pydantic AI Model configured from LLMConfig.

    Never reads environment variables directly — all config flows through cfg.
    The provider selection and credential extraction happen in the providers module.
    """
    if cfg.provider == "ollama":
        provider = build_ollama_provider(cfg)
    elif cfg.provider == "openai_compatible":
        provider = build_openai_compatible_provider(cfg)
    else:
        raise LLMConfigError(f"unsupported provider: {cfg.provider!r}")
    return OpenAIChatModel(cfg.model, provider=provider)
