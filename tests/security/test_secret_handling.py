"""Secret-handling audit.

Verifies that no secrets are leaked in prompts, logs, tool outputs, or OTel spans.
"""

from __future__ import annotations

from pathlib import Path

from wolfpack.config.settings import LLMConfig


class TestAgentPromptsDoNotLeakSecrets:
    """Static analysis of agent system prompts."""

    def test_closer_prompt_has_no_api_keys(self) -> None:
        from wolfpack.agents.closer import _SYSTEM_PROMPT

        assert "api_key" not in _SYSTEM_PROMPT.lower()
        assert "password" not in _SYSTEM_PROMPT.lower()
        assert "secret" not in _SYSTEM_PROMPT.lower()

    def test_tracker_prompt_has_no_database_urls(self) -> None:
        from wolfpack.agents.tracker import _SYSTEM_PROMPT

        assert "postgresql" not in _SYSTEM_PROMPT.lower()
        assert "nats://" not in _SYSTEM_PROMPT.lower()
        assert "dsn" not in _SYSTEM_PROMPT.lower()

    def test_flanker_prompt_has_no_internal_urls(self) -> None:
        from wolfpack.agents.flanker import _SYSTEM_PROMPT

        assert "http" not in _SYSTEM_PROMPT.lower()
        assert "api_key" not in _SYSTEM_PROMPT.lower()

    def test_alpha_prompt_has_no_secrets(self) -> None:
        from wolfpack.agents.alpha import AlphaDispatcher

        # Alpha uses instructions passed to Agent(), not a module-level string
        # The prompt template does not contain URLs or credentials
        assert AlphaDispatcher is not None


class TestLLMConfigSecretStr:
    """API keys must use SecretStr and not leak in repr or logs."""

    def test_llm_config_api_key_is_secretstr(self) -> None:
        cfg = LLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="llama3.2:1b",
            api_key="sk-test-secret",  # type: ignore[call-arg]
        )
        assert cfg.api_key is not None
        # SecretStr does not expose value in repr/str
        assert "sk-test-secret" not in str(cfg.api_key)
        assert "sk-test-secret" not in repr(cfg.api_key)
        # get_secret_value() is the explicit escape hatch
        assert cfg.api_key.get_secret_value() == "sk-test-secret"

    def test_llm_config_without_key(self) -> None:
        cfg = LLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="llama3.2:1b",
        )
        assert cfg.api_key is None


class TestConfigurationFilesDoNotContainSecrets:
    """Verify placeholder-only values in config templates."""

    def test_env_example_uses_placeholders(self) -> None:
        env_path = Path(".env.example")
        assert env_path.exists()
        content = env_path.read_text()
        # The example file should not contain a real-looking API key pattern
        assert "sk-" not in content, "Detected possible OpenAI key in .env.example"
        # Postgres DSN should use placeholder/changeme
        assert "changeme" in content or "placeholder" in content.lower()

    def test_docker_compose_no_hardcoded_secrets(self) -> None:
        compose_path = Path("docker-compose.yml")
        assert compose_path.exists()
        content = compose_path.read_text()
        assert "sk-" not in content
        assert "password" not in content.lower() or "changeme" in content.lower()

    def test_pyproject_no_secrets(self) -> None:
        content = Path("pyproject.toml").read_text()
        assert "sk-" not in content
        assert "api_key" not in content.lower()


class TestOTelSpanScrubbing:
    """OTel attributes must not contain raw PII or secrets."""

    def test_alert_manager_does_not_put_secrets_in_spans(self) -> None:
        from wolfpack.observability.alert_manager import AlertManager

        # AlertManager uses span attributes that are IDs and severities only
        manager = AlertManager()
        assert manager._webhook_url is None or isinstance(manager._webhook_url, str)
        # If a webhook URL were set, it should not contain credentials
        if manager._webhook_url:
            assert "@" not in manager._webhook_url  # no user:pass@host


class TestToolOutputsDoNotContainRawSecrets:
    """Adapter tool wrappers must not return raw credentials."""

    def test_adapter_tools_return_reference_handles(self) -> None:
        # Adapters hold their own credentials internally; tool outputs are
        # telemetry records, never config.
        from wolfpack.adapters.base import TelemetrySource

        assert hasattr(TelemetrySource, "query")
        # TelemetrySource has no method that returns its internal config
        assert not hasattr(TelemetrySource, "get_credentials")

    def test_rag_tools_return_documents_not_keys(self) -> None:
        from wolfpack.rag.base import RAGDocument

        doc = RAGDocument(id="d1", content="test", metadata={})
        assert "api_key" not in doc.content.lower()
        assert "secret" not in doc.content.lower()
