"""Bounded, source-free Provider preflight and circuit-breaker service."""

from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Protocol

from comic_agent.config import Settings
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.reliability import (
    ProviderCircuitStateV1,
    ProviderFailureCategory,
    ProviderHealthResultV1,
    ProviderHealthStatus,
    ProviderPreflightResponseV1,
)
from comic_agent.services.narrative_analyst_summary import classify_exception


class CircuitStore(Protocol):
    def get(self, provider_key: str) -> ProviderCircuitStateV1 | None: ...

    def save(self, state: ProviderCircuitStateV1) -> ProviderCircuitStateV1: ...


class ProviderHealthService:
    """Probe a Provider without source text and persist conservative pause state."""

    def __init__(self, *, settings: Settings, repository: CircuitStore) -> None:
        self._settings = settings
        self._repository = repository

    def preflight(self, *, provider_key: str, provider: LLMProvider) -> ProviderHealthResultV1:
        """Return a safe availability result without ever recording raw errors."""

        now = datetime.now(UTC)
        state = self._repository.get(provider_key)
        if state is not None and state.status == ProviderHealthStatus.CONFIGURATION_ERROR:
            return ProviderHealthResultV1(
                provider_key=provider_key,
                status=state.status,
                failure_category=state.last_failure_category,
                safe_issue_codes=["PROVIDER_CONFIGURATION_ERROR"],
                next_eligible_retry_at=state.next_eligible_retry_at,
            )
        if (
            state is not None
            and state.status in {ProviderHealthStatus.PAUSED, ProviderHealthStatus.WAITING_RETRY}
            and state.next_eligible_retry_at is not None
            and state.next_eligible_retry_at > now
        ):
            return ProviderHealthResultV1(
                provider_key=provider_key,
                status=state.status,
                failure_category=state.last_failure_category,
                safe_issue_codes=["PROVIDER_CIRCUIT_OPEN"],
                next_eligible_retry_at=state.next_eligible_retry_at,
            )
        started = monotonic()
        try:
            preflight = getattr(provider, "preflight", None)
            if callable(preflight):
                preflight()
            else:
                provider.structured_generate(
                    {
                        "system_prompt": "Return only the required readiness JSON.",
                        "user_prompt": "Readiness probe. Do not use external context.",
                        "input_context": {"preflight": True},
                    },
                    ProviderPreflightResponseV1,
                )
        except Exception as exc:
            category = self._category(exc)
            return self._record_failure(provider_key=provider_key, category=category, now=now)
        latency_ms = int((monotonic() - started) * 1000)
        if latency_ms > self._settings.provider_preflight_max_latency_ms:
            return self._record_failure(
                provider_key=provider_key,
                category=ProviderFailureCategory.TIMEOUT,
                now=now,
            )
        self._repository.save(
            ProviderCircuitStateV1(provider_key=provider_key, updated_at=now)
        )
        return ProviderHealthResultV1(
            provider_key=provider_key,
            status=ProviderHealthStatus.AVAILABLE,
            latency_ms=latency_ms,
        )

    def _record_failure(
        self,
        *,
        provider_key: str,
        category: ProviderFailureCategory,
        now: datetime,
    ) -> ProviderHealthResultV1:
        previous = self._repository.get(provider_key)
        failures = (previous.consecutive_failures if previous is not None else 0) + 1
        terminal = category in {
            ProviderFailureCategory.AUTH,
            ProviderFailureCategory.INVALID_CONFIGURATION,
        }
        delay = min(
            self._settings.provider_circuit_max_backoff_seconds,
            self._settings.provider_circuit_backoff_seconds * (2 ** min(failures - 1, 8)),
        )
        retry_at = now + timedelta(seconds=delay)
        status = (
            ProviderHealthStatus.CONFIGURATION_ERROR
            if terminal
            else ProviderHealthStatus.PAUSED
            if failures >= self._settings.provider_circuit_failure_threshold
            else ProviderHealthStatus.WAITING_RETRY
        )
        state = ProviderCircuitStateV1(
            provider_key=provider_key,
            status=status,
            consecutive_failures=failures,
            last_failure_category=category,
            last_failure_at=now,
            next_eligible_retry_at=retry_at,
            updated_at=now,
        )
        self._repository.save(state)
        return ProviderHealthResultV1(
            provider_key=provider_key,
            status=status,
            failure_category=category,
            safe_issue_codes=[str(category), "PROVIDER_CIRCUIT_OPEN"],
            next_eligible_retry_at=retry_at,
        )

    @staticmethod
    def _category(exc: BaseException) -> ProviderFailureCategory:
        category = classify_exception(exc)
        diagnostics = getattr(exc, "diagnostics", None)
        status_code = diagnostics.get("http_status_code") if isinstance(diagnostics, dict) else None
        if status_code in {401, 403}:
            return ProviderFailureCategory.AUTH
        if status_code == 429:
            return ProviderFailureCategory.RATE_LIMITED
        if isinstance(status_code, int) and status_code >= 500:
            return ProviderFailureCategory.SERVER
        return {
            "PROVIDER_TIMEOUT": ProviderFailureCategory.TIMEOUT,
            "PROVIDER_CONNECTION_ERROR": ProviderFailureCategory.CONNECTION,
            "SCHEMA_VALIDATION_FAILED": ProviderFailureCategory.SCHEMA,
        }.get(category, ProviderFailureCategory.UNKNOWN)
