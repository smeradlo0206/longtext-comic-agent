"""Regression coverage for source-free Provider preflight and circuit state."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from comic_agent.config import Settings
from comic_agent.schemas.reliability import (
    ProviderCircuitStateV1,
    ProviderFailureCategory,
    ProviderHealthStatus,
)
from comic_agent.services.provider_health_service import ProviderHealthService


class _MemoryCircuitStore:
    def __init__(self) -> None:
        self.value: ProviderCircuitStateV1 | None = None

    def get(self, provider_key: str) -> ProviderCircuitStateV1 | None:
        if self.value is None or self.value.provider_key != provider_key:
            return None
        return self.value

    def save(self, state: ProviderCircuitStateV1) -> ProviderCircuitStateV1:
        self.value = state
        return state


class _Provider:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    def structured_generate(
        self, request: dict[str, object], output_model: type[BaseModel]
    ) -> BaseModel:
        self.calls += 1
        assert request["input_context"] == {"preflight": True}
        if self.error is not None:
            raise self.error
        return output_model.model_validate({"ready": True})


class _HttpError(ValueError):
    def __init__(self, status_code: int) -> None:
        super().__init__("provider request failed")
        self.diagnostics = {"http_status_code": status_code}


def _settings(**updates: object) -> Settings:
    return Settings(
        _env_file=None,
        provider_circuit_failure_threshold=2,
        provider_circuit_backoff_seconds=1,
        provider_circuit_max_backoff_seconds=4,
        **updates,
    )


def test_preflight_success_is_source_free_and_resets_circuit() -> None:
    store = _MemoryCircuitStore()
    result = ProviderHealthService(settings=_settings(), repository=store).preflight(
        provider_key="local-test",
        provider=_Provider(),  # type: ignore[arg-type]
    )

    assert result.status == ProviderHealthStatus.AVAILABLE
    assert result.failure_category is None
    assert result.safe_issue_codes == []
    assert store.value is not None
    assert store.value.consecutive_failures == 0
    assert "prompt" not in result.model_dump_json()


def test_timeout_opens_waiting_circuit_then_pauses_without_recalling_provider() -> None:
    store = _MemoryCircuitStore()
    service = ProviderHealthService(settings=_settings(), repository=store)
    failing = _Provider(TimeoutError("secret source text"))

    first = service.preflight(provider_key="local-test", provider=failing)  # type: ignore[arg-type]
    second = service.preflight(provider_key="local-test", provider=failing)  # type: ignore[arg-type]

    assert first.status == ProviderHealthStatus.WAITING_RETRY
    assert first.failure_category == ProviderFailureCategory.TIMEOUT
    assert second.status == ProviderHealthStatus.WAITING_RETRY
    assert failing.calls == 1
    assert "secret source text" not in second.model_dump_json()


def test_auth_is_configuration_error_without_retry() -> None:
    store = _MemoryCircuitStore()
    provider = _Provider(_HttpError(401))
    service = ProviderHealthService(settings=_settings(), repository=store)
    result = service.preflight(
        provider_key="local-test", provider=provider  # type: ignore[arg-type]
    )
    second = service.preflight(
        provider_key="local-test", provider=provider  # type: ignore[arg-type]
    )

    assert result.status == ProviderHealthStatus.CONFIGURATION_ERROR
    assert result.failure_category == ProviderFailureCategory.AUTH
    assert second.status == ProviderHealthStatus.CONFIGURATION_ERROR
    assert provider.calls == 1


def test_expired_circuit_allows_a_new_safe_preflight() -> None:
    store = _MemoryCircuitStore()
    store.value = ProviderCircuitStateV1(
        provider_key="local-test",
        status=ProviderHealthStatus.PAUSED,
        consecutive_failures=2,
        last_failure_category=ProviderFailureCategory.RATE_LIMITED,
        next_eligible_retry_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    provider = _Provider()

    result = ProviderHealthService(settings=_settings(), repository=store).preflight(
        provider_key="local-test", provider=provider  # type: ignore[arg-type]
    )

    assert result.status == ProviderHealthStatus.AVAILABLE
    assert provider.calls == 1
