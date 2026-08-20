"""Application configuration."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
        default="https://api.llm.ustc.edu.cn/v1",
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
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
    llm_timeout_seconds: int = Field(
        default=60,
        gt=0,
        validation_alias="LLM_TIMEOUT_SECONDS",
    )
    provider_preflight_max_latency_ms: int = Field(
        default=10_000,
        ge=100,
        le=120_000,
        validation_alias="PROVIDER_PREFLIGHT_MAX_LATENCY_MS",
    )
    provider_circuit_failure_threshold: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="PROVIDER_CIRCUIT_FAILURE_THRESHOLD",
    )
    provider_circuit_backoff_seconds: int = Field(
        default=30,
        ge=1,
        le=3_600,
        validation_alias="PROVIDER_CIRCUIT_BACKOFF_SECONDS",
    )
    provider_circuit_max_backoff_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        validation_alias="PROVIDER_CIRCUIT_MAX_BACKOFF_SECONDS",
    )
    narrative_batch_max_chunks: int = Field(
        default=20,
        ge=1,
        le=200,
        validation_alias="NARRATIVE_BATCH_MAX_CHUNKS",
    )
    narrative_window_max_call_attempts: int = Field(
        default=2,
        ge=1,
        le=10,
        validation_alias="NARRATIVE_WINDOW_MAX_CALL_ATTEMPTS",
    )
    narrative_window_time_budget_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        validation_alias="NARRATIVE_WINDOW_TIME_BUDGET_SECONDS",
    )
    narrative_window_max_split_depth: int = Field(
        default=1,
        ge=0,
        le=8,
        validation_alias="NARRATIVE_WINDOW_MAX_SPLIT_DEPTH",
    )
    enable_real_llm: bool = Field(default=False, validation_alias="ENABLE_REAL_LLM")
    comic_agent_env: str = Field(default="production", validation_alias="COMIC_AGENT_ENV")
    fake_pipeline_demo: bool = Field(
        default=False,
        validation_alias="COMIC_AGENT_FAKE_PIPELINE_DEMO",
    )
    fake_pipeline_scenario: str = Field(
        default="success",
        validation_alias="COMIC_AGENT_FAKE_PIPELINE_SCENARIO",
    )
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
        default=False,
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

    @model_validator(mode="after")
    def validate_fake_pipeline_demo(self) -> "Settings":
        """Keep the deterministic demo provider unavailable in production or real-LLM mode."""

        if not self.fake_pipeline_demo:
            return self
        if self.comic_agent_env not in {"development", "test"}:
            raise ValueError("COMIC_AGENT_FAKE_PIPELINE_DEMO requires development or test")
        if self.enable_real_llm:
            raise ValueError("COMIC_AGENT_FAKE_PIPELINE_DEMO cannot enable real LLM")
        if self.fake_pipeline_scenario not in {"success", "recover_gate2", "recover_gate3"}:
            raise ValueError("COMIC_AGENT_FAKE_PIPELINE_SCENARIO is not supported")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
