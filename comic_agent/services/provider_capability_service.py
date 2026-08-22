"""Source-free, cached structured-output capability negotiation."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from comic_agent.config import Settings
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    EntityProposalBatchV1,
    EventProposalBatchV1,
    KnowledgeStateProposalBatchV1,
    RelationshipSignalProposalBatchV1,
    StateChangeProposalBatchV1,
)
from comic_agent.schemas.reliability import (
    ProviderCapabilityProfileV1,
    ProviderCapabilityState,
    ProviderFailureCategory,
    ProviderSchemaCapabilityV1,
    StructuredOutputMode,
    StructuredOutputPolicy,
)
from comic_agent.schemas.timeline import TimelinePairInferenceV1
from comic_agent.services.narrative_analyst_summary import classify_exception


class CapabilityStore(Protocol):
    def get_capability_profile(self, provider_key: str) -> ProviderCapabilityProfileV1 | None: ...

    def save_capability_profile(
        self, profile: ProviderCapabilityProfileV1
    ) -> ProviderCapabilityProfileV1: ...


class ProviderCapabilityService:
    """Resolve source-free base and per-output-Schema capabilities until TTL expiry."""

    _OUTPUT_MODELS: tuple[type[BaseModel], ...] = (
        EntityProposalBatchV1,
        EventProposalBatchV1,
        ClaimProposalBatchV1,
        KnowledgeStateProposalBatchV1,
        StateChangeProposalBatchV1,
        RelationshipSignalProposalBatchV1,
        TimelinePairInferenceV1,
    )

    def __init__(self, *, settings: Settings, repository: CapabilityStore) -> None:
        self._settings = settings
        self._repository = repository

    def resolve(
        self,
        *,
        provider_key: str,
        provider: LLMProvider,
        policy: StructuredOutputPolicy | None = None,
    ) -> ProviderCapabilityProfileV1:
        cached = self._repository.get_capability_profile(provider_key)
        now = datetime.now(UTC)
        if cached is not None and (cached.expires_at is None or cached.expires_at > now):
            self._apply(provider, cached)
            return cached

        effective_policy = policy or self._settings.llm_structured_output_policy
        probe = getattr(provider, "probe_structured_output", None)
        if not callable(probe):
            profile = self._unsupported_profile(provider_key, effective_policy, now)
        else:
            try:
                profile = probe(effective_policy)
                profile = self._with_schema_capabilities(
                    provider=provider,
                    profile=profile,
                    policy=effective_policy,
                )
            except Exception as exc:
                profile = self._failed_profile(provider_key, exc, now)
        profile = profile.model_copy(
            update={
                "checked_at": now,
                "expires_at": now
                + timedelta(seconds=self._settings.provider_capability_ttl_seconds),
            }
        )
        self._repository.save_capability_profile(profile)
        self._apply(provider, profile)
        return profile

    def _with_schema_capabilities(
        self,
        *,
        provider: LLMProvider,
        profile: ProviderCapabilityProfileV1,
        policy: StructuredOutputPolicy,
    ) -> ProviderCapabilityProfileV1:
        """Probe each actual Narrative/Timeline Provider contract without source text.

        A provider accepting a tiny readiness object is not evidence that it can
        satisfy our constrained Proposal batches and pair inference. Providers that do not
        offer this optional capability remain compatible, but cannot claim a
        per-Schema strict guarantee.
        """

        probe_schema = getattr(provider, "probe_output_schema", None)
        if not callable(probe_schema) or profile.state != ProviderCapabilityState.AVAILABLE:
            return profile

        capabilities = []
        for output_model in self._OUTPUT_MODELS:
            try:
                capabilities.append(probe_schema(policy, output_model))
            except Exception as exc:
                capabilities.append(
                    self._failed_schema_capability(
                        output_schema_name=output_model.__name__,
                        exc=exc,
                    )
                )
        return profile.model_copy(
            update={"schema_version": "1.1", "schema_capabilities": capabilities}
        )

    @staticmethod
    def _failed_schema_capability(
        *, output_schema_name: str, exc: BaseException
    ) -> ProviderSchemaCapabilityV1:
        category = classify_exception(exc)
        return ProviderSchemaCapabilityV1(
            output_schema_name=output_schema_name,
            state=ProviderCapabilityState.FAILED,
            supports_json_object=False,
            supports_strict_json_schema=False,
            selected_output_mode=StructuredOutputMode.UNAVAILABLE,
            safe_issue_codes=[
                "OUTPUT_SCHEMA_PREFLIGHT_FAILED",
                "SCHEMA_VALIDATION_FAILED"
                if category == "SCHEMA_VALIDATION_FAILED"
                else "OUTPUT_SCHEMA_PROBE_ERROR",
            ],
        )

    @staticmethod
    def _apply(provider: LLMProvider, profile: ProviderCapabilityProfileV1) -> None:
        apply = getattr(provider, "apply_capability_profile", None)
        if callable(apply):
            apply(profile)

    @staticmethod
    def _identity(provider_key: str) -> tuple[str, str]:
        provider_name, separator, model_name = provider_key.partition(":")
        return (
            provider_name or "configured-provider",
            model_name if separator else "configured-model",
        )

    def _unsupported_profile(
        self, provider_key: str, policy: StructuredOutputPolicy, now: datetime
    ) -> ProviderCapabilityProfileV1:
        provider_name, model_name = self._identity(provider_key)
        return ProviderCapabilityProfileV1(
            provider_name=provider_name,
            model_name=model_name,
            state=ProviderCapabilityState.UNSUPPORTED,
            supports_json_object=False,
            supports_strict_json_schema=False,
            supports_usage_reporting=False,
            supports_finish_reason=False,
            selected_output_mode=StructuredOutputMode.UNAVAILABLE,
            checked_at=now,
            safe_issue_codes=["UNSUPPORTED_STRUCTURED_OUTPUT", str(policy)],
        )

    def _failed_profile(
        self, provider_key: str, exc: BaseException, now: datetime
    ) -> ProviderCapabilityProfileV1:
        provider_name, model_name = self._identity(provider_key)
        diagnostics = getattr(exc, "diagnostics", None)
        status = diagnostics.get("http_status_code") if isinstance(diagnostics, dict) else None
        category = classify_exception(exc)
        return ProviderCapabilityProfileV1(
            provider_name=provider_name,
            model_name=model_name,
            state=ProviderCapabilityState.FAILED,
            supports_json_object=False,
            supports_strict_json_schema=False,
            supports_usage_reporting=False,
            supports_finish_reason=False,
            selected_output_mode=StructuredOutputMode.UNAVAILABLE,
            checked_at=now,
            error_category=(
                ProviderFailureCategory.SCHEMA
                if category == "SCHEMA_VALIDATION_FAILED"
                else ProviderFailureCategory.UNKNOWN
            ),
            http_status_code=status if isinstance(status, int) else None,
            safe_issue_codes=["STRUCTURED_OUTPUT_PREFLIGHT_FAILED"],
        )
