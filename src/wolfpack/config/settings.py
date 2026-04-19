"""Settings models for WolfPack services."""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from wolfpack.config.deployment import DeploymentMode, is_loopback_or_private


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai_compatible"]
    base_url: str
    model: str
    api_key: SecretStr | None = None
    hosted: bool = False
    request_timeout_s: float = 60.0


class PostgresConfig(BaseModel):
    dsn: SecretStr
    pool_min_size: int = 2
    pool_max_size: int = 10


class NATSConfig(BaseModel):
    url: str = "nats://localhost:4222"


class OTelConfig(BaseModel):
    endpoint: str = "http://localhost:4318"
    service_name: str = "wolfpack"
    service_namespace: str = "wolfpack"


class MLflowConfig(BaseModel):
    tracking_uri: str = "http://localhost:5000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    deployment_mode: DeploymentMode
    llm: LLMConfig
    postgres: PostgresConfig
    nats: NATSConfig = Field(default_factory=NATSConfig)
    otel: OTelConfig = Field(default_factory=OTelConfig)
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)

    @model_validator(mode="after")
    def enforce_airgapped(self) -> "Settings":
        if self.deployment_mode is not DeploymentMode.ON_PREM_AIRGAPPED:
            return self
        if self.llm.hosted:
            raise ValueError(
                "hosted LLM providers are forbidden in on_prem_airgapped mode"
            )
        if not is_loopback_or_private(self.llm.base_url):
            raise ValueError(
                "llm.base_url must resolve to a loopback or RFC-1918 private address "
                "in on_prem_airgapped mode"
            )
        return self
