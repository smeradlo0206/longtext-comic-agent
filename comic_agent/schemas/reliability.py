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


class ProviderPreflightResponseV1(StrictBaseModel):
    """Small structured response used only for an opt-in Provider health probe."""

    schema_version: Literal["1.0"] = "1.0"
    ready: Literal[True] = True


class ProviderCircuitStateV1(StrictBaseModel):
    """Persisted source-free circuit state for a configured Provider identity."""

    schema_version: Literal["1.0"] = "1.0"
    provider_key: str = Field(min_length=1)
    status: ProviderHealthStatus = ProviderHealthStatus.AVAILABLE
    consecutive_failures: int = Field(default=0, ge=0)
    last_failure_category: ProviderFailureCategory | None = None
    last_failure_at: datetime | None = None
    next_eligible_retry_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
