"""Errors raised by the LLM layer."""


class LLMConfigError(ValueError):
    """Raised when LLMConfig specifies an unsupported or invalid provider combination."""
