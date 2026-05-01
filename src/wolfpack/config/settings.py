"""Settings models for WolfPack services."""

import json
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wolfpack.config.deployment import DeploymentMode, is_loopback_or_private

_ALLOWED_SCHEMES = {"http", "https"}


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai_compatible"]
    base_url: str
    model: str
    api_key: SecretStr | None = None
    hosted: bool = False
    request_timeout_s: float = 60.0

    @field_validator("request_timeout_s")
    @classmethod
    def _timeout_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("request_timeout_s must be positive")
        return v

    @field_validator("base_url")
    @classmethod
    def _validate_url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(
                f"base_url must use http or https scheme, got: {parsed.scheme!r}"
            )
        if not parsed.netloc:
            raise ValueError("base_url must have a host component")
        return v


class PostgresConfig(BaseModel):
    dsn: SecretStr
    pool_min_size: int = 2
    pool_max_size: int = 10

    @model_validator(mode="after")
    def _pool_sizes_consistent(self) -> "PostgresConfig":
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(
                f"pool_min_size ({self.pool_min_size}) must not exceed "
                f"pool_max_size ({self.pool_max_size})"
            )
        return self


class NATSConfig(BaseModel):
    url: str = "nats://localhost:4222"


class OTelConfig(BaseModel):
    endpoint: str = "http://localhost:4318"
    service_name: str = "wolfpack"
    service_namespace: str = "wolfpack"


class MLflowConfig(BaseModel):
    tracking_uri: str = "http://localhost:5000"


class BranchBudgetConfig(BaseModel):
    max_depth: int = 3
    max_branches_per_case: int = 10
    # NOTE: token_budget_per_branch and tool_budget_per_branch are
    # reserved for V2. They require LLM-provider instrumentation that
    # is not yet wired into the graph nodes. Only depth and branch
    # count are enforced in V1.


class WebhookConfig(BaseModel):
    """Webhook target for alert and timeout escalation notifications."""

    url: str | None = None
    timeout_s: float = 30.0


class LearningConfig(BaseModel):
    """Configuration for the learning queue worker."""

    schedule_minutes: int = 5
    batch_size: int = 50
    retry_limit: int = 3
    min_confidence: int = 3
    enable_worker: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    deployment_mode: DeploymentMode
    llm: LLMConfig
    postgres: PostgresConfig
    nats: NATSConfig = Field(default_factory=NATSConfig)
    otel: OTelConfig = Field(default_factory=OTelConfig)
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    branch_budget: BranchBudgetConfig = Field(default_factory=BranchBudgetConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    webhook_config: WebhookConfig = Field(default_factory=WebhookConfig)

    @field_validator("webhook_config", mode="before")
    @classmethod
    def _parse_webhook(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"url": v}
        return v

    @field_validator("feature_flags", mode="before")
    @classmethod
    def _parse_feature_flags(cls, v: Any) -> Any:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @model_validator(mode="after")
    def _merge_feature_flag_defaults(self) -> "Settings":
        defaults = {
            "adapter_dns": False,
            "adapter_zeek_suricata": False,
            "adapter_proxy": False,
            "adapter_cloudtrail": False,
        }
        for key, val in defaults.items():
            self.feature_flags.setdefault(key, val)
        return self

    @model_validator(mode="after")
    def enforce_airgapped(self) -> "Settings":
        if self.deployment_mode is not DeploymentMode.ON_PREM_AIRGAPPED:
            return self
        if self.llm.hosted:
            raise ValueError("hosted LLM providers are forbidden in on_prem_airgapped mode")
        if not is_loopback_or_private(self.llm.base_url):
            raise ValueError(
                "llm.base_url must resolve to a loopback or RFC-1918 private address "
                "in on_prem_airgapped mode"
            )
        return self
