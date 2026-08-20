"""Source-free contracts for bounded Provider availability checks."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class ProviderHealthStatus(StrEnum):
    """Safe availability states; none exposes provider response content."""

    AVAILABLE = "AVAILABLE"
    WAITING_RETRY = "WAITING_RETRY"
    PAUSED = "PAUSED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class ProviderFailureCategory(StrEnum):
    """Fixed, source-free Provider failure classifications."""

    TIMEOUT = "PROVIDER_TIMEOUT"
    CONNECTION = "PROVIDER_CONNECTION_ERROR"
    RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    SERVER = "PROVIDER_SERVER_ERROR"
    AUTH = "PROVIDER_AUTH_ERROR"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    SCHEMA = "SCHEMA_VALIDATION_FAILED"
    UNKNOWN = "PROVIDER_UNKNOWN_ERROR"


class ProviderCapabilityState(StrEnum):
    """Safe outcome of a source-free structured-output capability probe."""

    AVAILABLE = "AVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class StructuredOutputMode(StrEnum):
    """The only structured-output transport modes accepted by Narrative execution."""

    STRICT_JSON_SCHEMA = "STRICT_JSON_SCHEMA"
    JSON_OBJECT = "JSON_OBJECT"
    PROMPT_ONLY = "PROMPT_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class StructuredOutputPolicy(StrEnum):
    """Operator-selected capability policy; never inferred from a failed source call."""

    AUTO = "AUTO"
    REQUIRE_STRICT = "REQUIRE_STRICT"
    JSON_OBJECT_ONLY = "JSON_OBJECT_ONLY"


class ProviderSchemaCapabilityV1(StrictBaseModel):
    """Source-free structured-output capability for one concrete output Schema."""

    schema_version: Literal["1.0"] = "1.0"
    output_schema_name: str = Field(min_length=1)
    state: ProviderCapabilityState
    supports_json_object: bool
    supports_strict_json_schema: bool
    selected_output_mode: StructuredOutputMode
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    safe_issue_codes: list[str] = Field(default_factory=list)


class ProviderCapabilityProfileV1(StrictBaseModel):
    """Persisted, source-free structured-output capability result."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    state: ProviderCapabilityState
    supports_json_object: bool
    supports_strict_json_schema: bool
    supports_usage_reporting: bool
    supports_finish_reason: bool
    selected_output_mode: StructuredOutputMode
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    error_category: ProviderFailureCategory | None = None
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    safe_issue_codes: list[str] = Field(default_factory=list)
    schema_capabilities: list[ProviderSchemaCapabilityV1] = Field(default_factory=list)


class ProviderExecutionMetadataV1(StrictBaseModel):
    """Allowlisted metadata retained after a structured Provider response."""

    schema_version: Literal["1.0"] = "1.0"
    selected_output_mode: StructuredOutputMode
    capability_state: ProviderCapabilityState | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    expected_output_schema: str | None = None
    schema_diagnostics: dict[str, object] | None = None


class ProviderPreflightResponseV1(StrictBaseModel):
    """Small structured response used only for an opt-in Provider health probe."""

    schema_version: Literal["1.0"] = "1.0"
    ready: Literal[True] = True


class ProviderCircuitStateV1(StrictBaseModel):
    """Persisted source-free circuit state for a configured Provider identity."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    provider_key: str = Field(min_length=1)
    status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE
    consecutive_failures: int = Field(default=0, ge=0)
    last_failure_category: ProviderFailureCategory | None = None
    last_failure_at: datetime | None = None
    next_eligible_retry_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    capability_profile: ProviderCapabilityProfileV1 | None = None


class ProviderHealthResultV1(StrictBaseModel):
    """Typed and redacted health/preflight response for API and Console."""

    schema_version: Literal["1.0"] = "1.0"
    provider_key: str = Field(min_length=1)
    status: ProviderHealthStatus
    failure_category: ProviderFailureCategory | None = None
    safe_issue_codes: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    next_eligible_retry_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
