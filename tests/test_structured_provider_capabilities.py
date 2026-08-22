"""Regression coverage for negotiated structured Provider execution."""

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.config import Settings
from comic_agent.providers.openai_compatible import OpenAICompatibleLLMProvider
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.reliability import (
    ProviderCapabilityProfileV1,
    ProviderCapabilityState,
    ProviderSchemaCapabilityV1,
    StructuredOutputMode,
    StructuredOutputPolicy,
)
from comic_agent.services.provider_capability_service import ProviderCapabilityService


class _Output(BaseModel):
    answer: str


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _StatusResponse(_Response):
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        super().__init__(payload)
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("mock status", request=request, response=response)


class _ProbeClient:
    def __init__(self, responses: list[_StatusResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def post(
        self, url: str, headers: dict[str, str], json: dict[str, Any], timeout: int
    ) -> _StatusResponse:
        self.requests.append(json)
        return self.responses.pop(0)


class _Client:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def post(
        self, url: str, headers: dict[str, str], json: dict[str, Any], timeout: int
    ) -> _Response:
        self.requests.append(json)
        return _Response(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"answer":"ok"}'}}
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
        )


class _Store:
    def __init__(self) -> None:
        self.value: ProviderCapabilityProfileV1 | None = None

    def get_capability_profile(
        self, provider_key: str
    ) -> ProviderCapabilityProfileV1 | None:
        return self.value

    def save_capability_profile(
        self, profile: ProviderCapabilityProfileV1
    ) -> ProviderCapabilityProfileV1:
        self.value = profile
        return profile


class _ProbeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.schema_calls: list[str] = []

    def probe_structured_output(
        self, policy: StructuredOutputPolicy
    ) -> ProviderCapabilityProfileV1:
        self.calls += 1
        return ProviderCapabilityProfileV1(
            provider_name="fake",
            model_name="fake-model",
            state=ProviderCapabilityState.AVAILABLE,
            supports_json_object=True,
            supports_strict_json_schema=True,
            supports_usage_reporting=True,
            supports_finish_reason=True,
            selected_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
        )

    def probe_output_schema(
        self, policy: StructuredOutputPolicy, output_model: type[BaseModel]
    ) -> ProviderSchemaCapabilityV1:
        self.schema_calls.append(output_model.__name__)
        return ProviderSchemaCapabilityV1(
            output_schema_name=output_model.__name__,
            state=ProviderCapabilityState.AVAILABLE,
            supports_json_object=True,
            supports_strict_json_schema=True,
            selected_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
        )


def test_strict_profile_sends_openai_json_schema_and_preserves_execution_metadata() -> None:
    client = _Client()
    provider = OpenAICompatibleLLMProvider(
        api_key="secret",
        http_client=client,
        structured_output_policy=StructuredOutputPolicy.AUTO,
    )
    provider.apply_capability_profile(
        ProviderCapabilityProfileV1(
            provider_name="ustc-openai-compatible",
            model_name="deepseek-v4-pro",
            state=ProviderCapabilityState.AVAILABLE,
            supports_json_object=True,
            supports_strict_json_schema=True,
            supports_usage_reporting=True,
            supports_finish_reason=True,
            selected_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
        )
    )

    assert provider.structured_generate(
        {"user_prompt": "source must not be copied here"}, _Output
    ) == _Output(answer="ok")
    assert client.requests[0]["response_format"]["type"] == "json_schema"
    assert client.requests[0]["response_format"]["json_schema"]["strict"] is True
    metadata = provider.last_execution_metadata()
    assert metadata.finish_reason == "stop"
    assert metadata.completion_tokens == 3
    assert "source must not be copied here" not in metadata.model_dump_json()


def test_schema_specific_capability_overrides_provider_wide_mode() -> None:
    client = _Client()
    provider = OpenAICompatibleLLMProvider(
        api_key="secret",
        http_client=client,
        structured_output_policy=StructuredOutputPolicy.AUTO,
    )
    provider.apply_capability_profile(
        ProviderCapabilityProfileV1(
            provider_name="ustc-openai-compatible",
            model_name="deepseek-v4-pro",
            state=ProviderCapabilityState.AVAILABLE,
            supports_json_object=True,
            supports_strict_json_schema=True,
            supports_usage_reporting=True,
            supports_finish_reason=True,
            selected_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
            schema_capabilities=[
                ProviderSchemaCapabilityV1(
                    output_schema_name="_Output",
                    state=ProviderCapabilityState.AVAILABLE,
                    supports_json_object=True,
                    supports_strict_json_schema=False,
                    selected_output_mode=StructuredOutputMode.JSON_OBJECT,
                )
            ],
        )
    )

    assert provider.structured_generate({}, _Output) == _Output(answer="ok")
    assert client.requests[0]["response_format"] == {"type": "json_object"}


def test_capability_service_caches_source_free_probe_until_ttl() -> None:
    store = _Store()
    provider = _ProbeProvider()
    service = ProviderCapabilityService(settings=Settings(_env_file=None), repository=store)

    first = service.resolve(provider_key="fake:fake-model", provider=provider)
    second = service.resolve(provider_key="fake:fake-model", provider=provider)

    assert first.selected_output_mode == StructuredOutputMode.STRICT_JSON_SCHEMA
    assert second == first
    assert provider.calls == 1
    assert len(first.schema_capabilities) == 7
    assert "TimelinePairInferenceV1" in {
        item.output_schema_name for item in first.schema_capabilities
    }
    assert len(provider.schema_calls) == 7


def test_schema_probe_uses_each_concrete_schema_and_json_object_fallback() -> None:
    client = _ProbeClient(
        [
            _StatusResponse(400, {}),
            _StatusResponse(
                200,
                {"choices": [{"message": {"content": "{}"}}]},
            ),
        ]
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="secret", http_client=client, structured_output_policy=StructuredOutputPolicy.AUTO
    )

    capability = provider.probe_output_schema(StructuredOutputPolicy.AUTO, _Output)

    assert capability.output_schema_name == "_Output"
    assert capability.selected_output_mode == StructuredOutputMode.JSON_OBJECT
    assert [item["response_format"]["type"] for item in client.requests] == [
        "json_schema",
        "json_object",
    ]
    assert (
        client.requests[0]["response_format"]["json_schema"]["schema"]
        == _Output.model_json_schema()
    )


def test_auto_probe_falls_back_to_json_object_only_for_explicit_strict_rejection() -> None:
    client = _ProbeClient(
        [
            _StatusResponse(400, {}),
            _StatusResponse(
                200,
                {"choices": [{"message": {"content": '{"ready":true}'}}]},
            ),
        ]
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="secret", http_client=client, structured_output_policy=StructuredOutputPolicy.AUTO
    )

    profile = provider.probe_structured_output(StructuredOutputPolicy.AUTO)

    assert profile.selected_output_mode == StructuredOutputMode.JSON_OBJECT
    assert [item["response_format"]["type"] for item in client.requests] == [
        "json_schema",
        "json_object",
    ]
    assert all("source_chunks" not in json.dumps(item) for item in client.requests)


def test_require_strict_stops_when_probe_proves_it_unsupported() -> None:
    client = _ProbeClient([_StatusResponse(400, {})])
    provider = OpenAICompatibleLLMProvider(api_key="secret", http_client=client)

    profile = provider.probe_structured_output(StructuredOutputPolicy.REQUIRE_STRICT)

    assert profile.state == ProviderCapabilityState.UNSUPPORTED
    assert profile.selected_output_mode == StructuredOutputMode.UNAVAILABLE
    assert len(client.requests) == 1


def test_unknown_schema_errors_expose_only_safe_contract_diagnostics() -> None:
    with pytest.raises(ValidationError) as captured:
        _Output.model_validate({"answer": 3})
    diagnostics = OpenAICompatibleLLMProvider.schema_validation_diagnostics(captured.value, _Output)
    assert diagnostics["expected_output_schema"] == "_Output"
    assert diagnostics["schema_error_field_paths"] == ["answer"]
    assert "3" not in json.dumps(diagnostics)


def test_event_actor_rule_exposes_a_safe_repair_code() -> None:
    with pytest.raises(ValidationError) as captured:
        EventProposalV1.model_validate(
            {
                "proposal_id": "event-1",
                "event_type": "ACTION",
                "summary": "A bounded action.",
                "participant_ids": [],
                "actor_resolution_status": "KNOWN",
                "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1")],
                "confidence": 0.8,
                "reality_layer": RealityLayer.PRIMARY,
            }
        )

    diagnostics = OpenAICompatibleLLMProvider.schema_validation_diagnostics(
        captured.value, "EventProposalBatchV1"
    )

    assert diagnostics["schema_error_rule_codes"] == [
        "EVENT_KNOWN_ACTOR_REQUIRES_PARTICIPANT_IDS"
    ]


def test_event_schema_repair_instruction_allows_empty_or_complete_items() -> None:
    provider = OpenAICompatibleLLMProvider(api_key="test-key")

    instruction = provider._format_recovery_instruction(
        {
            "output_recovery": "schema_validation",
            "schema_error_rule_codes": ["EVENT_KNOWN_ACTOR_REQUIRES_PARTICIPANT_IDS"],
        },
        "EventProposalBatchV1",
    )

    assert "events may be empty" in instruction
    assert "EVENT_KNOWN_ACTOR_REQUIRES_PARTICIPANT_IDS" in instruction
    assert "actor_resolution_status" in instruction
