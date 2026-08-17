"""Application configuration."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "longtext-comic-agent"
    database_url: str = Field(
        default="sqlite+pysqlite:///./comic_agent.db",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="LLM_API_KEY",
    )
    storybible_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias="STORYBIBLE_MODEL",
    )
    timeline_model: str | None = Field(
        default=None,
        validation_alias="TIMELINE_MODEL",
        description="Optional TimelineAgent model; defaults to STORYBIBLE_MODEL.",
    )
    timeline_llm_enabled: bool = Field(
        default=False,
        validation_alias="TIMELINE_LLM_ENABLED",
    )
    timeline_llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        validation_alias="TIMELINE_LLM_TIMEOUT_SECONDS",
    )
    timeline_llm_max_retries: int = Field(
        default=1,
        ge=0,
        le=1,
        validation_alias="TIMELINE_LLM_MAX_RETRIES",
    )
    llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        validation_alias="LLM_TIMEOUT_SECONDS",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
