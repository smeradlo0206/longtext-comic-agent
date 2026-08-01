"""Application configuration."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

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
    llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        validation_alias="LLM_TIMEOUT_SECONDS",
    )
    enable_real_llm: bool = Field(default=False, validation_alias="ENABLE_REAL_LLM")
    llm_provider_name: str = Field(
        default="ustc-openai-compatible",
        validation_alias="LLM_PROVIDER_NAME",
    )
    llm_model: str = Field(default="deepseek-v4-pro", validation_alias="LLM_MODEL")
    llm_response_format: str | None = Field(
        default=None,
        validation_alias="LLM_RESPONSE_FORMAT",
    )
    llm_max_output_tokens: int = Field(default=2000, validation_alias="LLM_MAX_OUTPUT_TOKENS")
    internal_demo_require_access_code: bool = Field(
        default=True,
        validation_alias="INTERNAL_DEMO_REQUIRE_ACCESS_CODE",
    )
    internal_demo_access_code: SecretStr | None = Field(
        default=None,
        validation_alias="INTERNAL_DEMO_ACCESS_CODE",
    )
    internal_demo_session_ttl_seconds: int = Field(
        default=86400,
        validation_alias="INTERNAL_DEMO_SESSION_TTL_SECONDS",
    )
    internal_demo_max_real_event_chunks_per_run: int = Field(
        default=3,
        validation_alias="INTERNAL_DEMO_MAX_REAL_EVENT_CHUNKS_PER_RUN",
    )
    internal_demo_max_import_chars: int = Field(
        default=20000,
        validation_alias="INTERNAL_DEMO_MAX_IMPORT_CHARS",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
