import json
import os
import socket
import ssl
from typing import Any, Literal

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from comic_agent.config import Settings
from comic_agent.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
    OpenAICompatibleProvider,
    ProviderHttpError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    EntityProposalBatchV1,
    EventProposalBatchV1,
    EventProposalV1,
    KnowledgeStateProposalBatchV1,
    RelationshipSignalProposalBatchV1,
    StateChangeProposalBatchV1,
)
from comic_agent.schemas.reliability import StructuredOutputPolicy


class OutputModel(BaseModel):
    answer: str


class LiveSmokeOutput(BaseModel):
    status: Literal["ok"]


def _transport(
    response_content: str = '{"answer":"ok"}',
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": response_content}}]},
        )

    return httpx.MockTransport(handler), requests


def test_openai_provider_posts_json_request_with_key_only_in_authorization_header() -> None:
    transport, requests = _transport()
    provider = OpenAICompatibleProvider(
        base_url="https://api.example/v1/",
        api_key=SecretStr("test-api-key"),
        model="deepseek-v4-pro",
        transport=transport,
    )

    result = provider.structured_generate(
        {"messages": [{"role": "user", "content": "x"}]},
        OutputModel,
    )

    assert result == OutputModel(answer="ok")
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-api-key"
    assert "test-api-key" not in request.content.decode()
    assert json.loads(request.content) == {
        "messages": [{"role": "user", "content": "x"}],
        "model": "deepseek-v4-pro",
        "response_format": {"type": "json_object"},
    }


def test_openai_provider_validates_message_content_through_output_model() -> None:
    transport, _ = _transport('{"answer":42}')
    provider = OpenAICompatibleProvider(
        base_url="https://api.example/v1",
        api_key=SecretStr("test-api-key"),
        model="deepseek-v4-pro",
        transport=transport,
    )

    with pytest.raises(ValidationError):
        provider.structured_generate(
            {"messages": [{"role": "user", "content": "x"}]},
            OutputModel,
        )


def test_settings_load_openai_compatible_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-api-key")

    settings = Settings(_env_file=None)

    assert settings.llm_base_url == "https://api.example/v1"
    assert settings.llm_api_key.get_secret_value() == "test-api-key"
    assert settings.storybible_model == "deepseek-v4-pro"
    assert settings.llm_timeout_seconds == 60.0


def test_llm_output_token_budget_defaults_to_8000_and_honors_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    assert Settings(_env_file=None).llm_max_output_tokens == 8000

    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "8000")
    assert Settings(_env_file=None).llm_max_output_tokens == 8000


def test_real_provider_sends_configured_8000_output_token_budget() -> None:
    client = FakeHttpClient(
        FakeResponse(200, {"choices": [{"message": {"content": '{"answer":"ok"}'}}]})
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="secret",
        http_client=client,
        max_output_tokens=8000,
        structured_output_policy=StructuredOutputPolicy.JSON_OBJECT_ONLY,
    )

    assert provider.structured_generate({}, OutputModel) == OutputModel(answer="ok")
    assert client.requests[0]["json"]["max_tokens"] == 8000


def test_provider_without_cached_capability_profile_uses_json_object_not_prompt_only() -> None:
    client = FakeHttpClient(
        FakeResponse(200, {"choices": [{"message": {"content": '{"answer":"ok"}'}}]})
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="secret",
        http_client=client,
        structured_output_policy=StructuredOutputPolicy.JSON_OBJECT_ONLY,
    )

    assert provider.structured_generate({}, OutputModel) == OutputModel(answer="ok")
    assert client.requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_settings_redacts_llm_api_key_from_repr_and_model_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "credential-that-must-stay-secret"
    monkeypatch.setenv("LLM_API_KEY", secret)

    settings = Settings(_env_file=None)

    assert isinstance(settings.llm_api_key, SecretStr)
    assert secret not in repr(settings)
    assert secret not in repr(settings.model_dump())
    assert settings.model_dump(mode="json")["llm_api_key"] == "**********"


def test_openai_provider_rejects_malformed_top_level_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    provider = OpenAICompatibleProvider(
        base_url="https://api.example/v1",
        api_key=SecretStr("test-api-key"),
        model="deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(json.JSONDecodeError):
        provider.structured_generate(
            {"messages": [{"role": "user", "content": "x"}]},
            OutputModel,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "provider response must be a JSON object"),
        ({}, "provider response must contain at least one choice"),
        ({"choices": []}, "provider response must contain at least one choice"),
        ({"choices": [None]}, "provider choice must be a JSON object"),
        ({"choices": [{}]}, "provider choice must contain a message object"),
        (
            {"choices": [{"message": {}}]},
            "provider message content must be a JSON string",
        ),
    ],
)
def test_openai_provider_rejects_malformed_response_envelopes(
    payload: object,
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    provider = OpenAICompatibleProvider(
        base_url="https://api.example/v1",
        api_key=SecretStr("test-api-key"),
        model="deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match=f"^{message}$"):
        provider.structured_generate(
            {"messages": [{"role": "user", "content": "x"}]},
            OutputModel,
        )


def test_live_openai_compatible_connectivity_when_explicitly_enabled() -> None:
    if os.environ.get("RUN_LIVE_LLM_SMOKE_TEST") != "1":
        pytest.skip("set RUN_LIVE_LLM_SMOKE_TEST=1 to enable the live provider smoke test")

    required_names = ("LLM_BASE_URL", "LLM_API_KEY", "STORYBIBLE_MODEL")
    missing_names = [name for name in required_names if not os.environ.get(name)]
    if missing_names:
        message = "missing required live smoke-test environment variables: "
        pytest.fail(message + ", ".join(missing_names))

    settings = Settings(_env_file=None)
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.storybible_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )

    result = provider.structured_generate(
        {
            "messages": [
                {
                    "role": "user",
                    "content": 'Return exactly this JSON object: {"status":"ok"}',
                }
            ],
            "temperature": 0,
        },
        LiveSmokeOutput,
    )

    assert result.status == "ok"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "fake-response"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("http error", request=request, response=response)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeHttpClient:
    def __init__(
        self,
        response: FakeResponse | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.response = response
        self.exc = exc
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        if self.exc is not None:
            raise self.exc
        if self.response is None:
            raise AssertionError("FakeHttpClient response was not configured")
        return self.response


class SequenceHttpClient:
    """Return configured outcomes in request order for retry tests."""

    def __init__(self, outcomes: list[FakeResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RaisingHttpClient:
    def __init__(self, exc: Exception, cause: Exception | None = None) -> None:
        self.exc = exc
        self.cause = cause

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> FakeResponse:
        if self.cause is None:
            raise self.exc
        try:
            raise self.cause
        except Exception as cause:
            raise self.exc from cause


def _event_json() -> dict[str, Any]:
    return {
        "proposal_id": "proposal-1",
        "event_type": "handoff",
        "summary": "陈野把伞递给林夏。",
        "participant_ids": ["char-chen", "char-lin"],
        "actor_resolution_status": "KNOWN",
        "location_id": None,
        "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "伞递给"}],
        "confidence": 0.9,
        "reality_layer": "PRIMARY",
    }


def _event_batch_json() -> dict[str, Any]:
    return {"batch_id": "event-batch-1", "events": [_event_json()]}


def _knowledge_state_batch_json(*, target_kind: str) -> dict[str, Any]:
    target_text = "山中有鬼" if target_kind == "WORLD_FACT" else "山中有鬼的传言"
    return {
        "batch_id": "knowledge-batch-1",
        "states": [
            {
                "proposal_id": "knowledge-1",
                "subject": {
                    "mention_text": "林舟",
                    "entity_proposal_id": None,
                    "resolution_status": "UNRESOLVED",
                },
                "target": {
                    "target_kind": target_kind,
                    "target_text": target_text,
                    "proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "epistemic_status": "DISBELIEVES",
                "epistemic_basis": "STATED",
                "reality_layer": "PRIMARY",
                "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "不信山中有鬼"}],
                "confidence": 0.9,
            }
        ],
    }


def _state_change_batch_json(*, quantity_value: object = 4) -> dict[str, Any]:
    return {
        "schema_version": "1.3",
        "batch_id": "state-change-batch-1",
        "changes": [
            {
                "schema_version": "1.3",
                "proposal_id": "state-change-quantity-1",
                "event": {
                    "event_summary": "药瓶数量从六变为四",
                    "event_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "target": {
                    "mention_text": "药瓶",
                    "target_kind": "OBJECT",
                    "entity_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "attribute_path": "quantity",
                "old_value": 6,
                "new_value": quantity_value,
                "persistent": False,
                "reality_layer": "PRIMARY",
                "evidence_refs": [
                    {"chunk_id": "chunk-1", "quote_text": "药瓶数量从六变为四"}
                ],
                "new_value_evidence_indexes": [0],
                "persistence_evidence_indexes": [],
                "confidence": 0.9,
            }
        ],
    }


def _chat_response(
    content: Any,
    *,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    extra_message: dict[str, Any] | None = None,
) -> FakeResponse:
    message = {"content": content}
    if extra_message:
        message.update(extra_message)
    choice: dict[str, Any] = {"message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    payload: dict[str, Any] = {"choices": [choice]}
    if usage is not None:
        payload["usage"] = usage
    return FakeResponse(
        200,
        payload,
    )


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        (
            "v1.2 old_value for quantity must be numeric",
            "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER",
        ),
        ("v1.2 new_value must be a JSON scalar", "STATE_CHANGE_VALUE_MUST_BE_SCALAR"),
        (
            "v1.2 new_value_evidence_indexes contains an out-of-range index",
            "STATE_CHANGE_EVIDENCE_INDEX_OUT_OF_RANGE",
        ),
        (
            "v1.2 persistent=false requires persistence_evidence_indexes to be empty",
            "STATE_CHANGE_PERSISTENCE_INDEX_RULE",
        ),
        ("changes must have unique proposal_id values", "STATE_CHANGE_DUPLICATE_PROPOSAL_ID"),
        (
            "changes must not contain semantic duplicate state changes",
            "STATE_CHANGE_SEMANTIC_DUPLICATE",
        ),
        (
            "UNRESOLVED event requires proposal_id and proposal_schema to be null",
            "EVENT_REFERENCE_MUST_STAY_UNRESOLVED",
        ),
    ],
)
def test_state_change_schema_rule_codes_are_safe_and_stable(
    message: str, expected_code: str
) -> None:
    assert (
        OpenAICompatibleLLMProvider._schema_validation_rule_code({"msg": message})
        == expected_code
    )


def test_openai_compatible_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenAICompatibleLLMProvider(api_key=None)


def test_openai_compatible_provider_retries_one_tls_connect_error() -> None:
    """A transient TLS handshake failure gets one bounded retry before surfacing."""

    response = _chat_response(json.dumps(_event_json(), ensure_ascii=False))
    client = SequenceHttpClient(
        [httpx.ConnectError("TLS handshake failed"), response]
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"
    assert len(client.requests) == 2


def test_openai_compatible_provider_reports_tls_failure_after_bounded_retry() -> None:
    """Persistent TLS failure stays transparent and contains no endpoint details."""

    client = SequenceHttpClient(
        [httpx.ConnectError("TLS handshake failed"), httpx.ConnectError("TLS handshake failed")]
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    with pytest.raises(ProviderNetworkError, match="TLS handshake") as captured:
        provider.structured_generate({}, EventProposalV1)

    assert captured.value.diagnostics == {"request_attempts": 2}
    assert len(client.requests) == 2


def test_openai_compatible_provider_returns_event_proposal() -> None:
    client = FakeHttpClient(response=_chat_response(json.dumps(_event_json(), ensure_ascii=False)))
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    proposal = provider.structured_generate(
        {
            "system_prompt": "Extract one event.",
            "user_prompt": "Use source chunks.",
            "input_context": {
                "source_chunks": [{"chunk_id": "chunk-1", "text": "陈野把伞递给林夏。"}]
            },
        },
        EventProposalV1,
    )

    assert proposal.evidence_refs == [EvidenceRefV1(chunk_id="chunk-1", quote_text="伞递给")]
    assert proposal.reality_layer == RealityLayer.PRIMARY
    assert client.requests[0]["url"] == "https://api.llm.ustc.edu.cn/v1/chat/completions"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret-test-key"
    assert client.requests[0]["json"]["model"] == "deepseek-v4-pro"
    assert client.requests[0]["json"]["temperature"] == 0


def test_openai_compatible_provider_parses_standard_string_json_content() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(json.dumps(_event_json(), ensure_ascii=False))
        ),
    )

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"


def test_openai_compatible_provider_uses_json_object_by_default() -> None:
    client = FakeHttpClient(response=_chat_response(json.dumps(_event_json(), ensure_ascii=False)))
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    provider.structured_generate({}, EventProposalV1)

    assert client.requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_provider_sends_json_object_response_format() -> None:
    client = FakeHttpClient(response=_chat_response(json.dumps(_event_json(), ensure_ascii=False)))
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        response_format="json_object",
        http_client=client,
    )

    provider.structured_generate({}, EventProposalV1)

    assert client.requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_provider_sends_compact_resolved_output_contract() -> None:
    """Keep batch extraction requests small enough to reserve output budget for JSON."""

    response = _chat_response(json.dumps(_event_batch_json(), ensure_ascii=False))
    client = FakeHttpClient(response=response)
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    provider.structured_generate(
        {
            "system_prompt": "Extract evidence-backed events.",
            "user_prompt": "Return one event batch.",
            "input_context": {"source_chunks": [{"chunk_id": "chunk-1", "text": "正文。"}]},
        },
        EventProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert "Output contract:" in user_message
    assert '"events"' in user_message
    assert '"quote_text"' in user_message
    assert '"actor_resolution_status"' in user_message
    assert '"$defs"' not in user_message
    assert '"$ref"' not in user_message
    assert len(user_message) < 2600


def test_openai_compatible_provider_adds_fixed_schema_recovery_instruction() -> None:
    client = FakeHttpClient(
        response=_chat_response(json.dumps(_event_batch_json(), ensure_ascii=False))
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    provider.structured_generate(
        {
            "input_context": {
                "output_recovery": "schema_validation",
                "source_chunks": [{"chunk_id": "chunk-1", "text": "Synthetic source."}],
            }
        },
        EventProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert "Format recovery instruction:" in user_message
    assert "exactly one EventProposalBatchV1 JSON object" in user_message
    assert "events may be empty" in user_message
    assert "actor_resolution_status" in user_message


def test_state_change_schema_recovery_instruction_is_numeric_and_source_free() -> None:
    client = FakeHttpClient(
        response=_chat_response(json.dumps(_state_change_batch_json(), ensure_ascii=False))
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    recovered = provider.structured_generate(
        {
            "input_context": {
                "output_recovery": "state_change_schema_recovery",
                "schema_error_rule_codes": ["STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER"],
                "source_chunks": [{"chunk_id": "chunk-1", "text": "敏感原文不应进入固定指令。"}],
            }
        },
        StateChangeProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert recovered.changes[0].new_value == 4
    assert "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER" in user_message
    assert "quantity old_value and new_value must be JSON numbers" in user_message
    assert 'wrong "4", "四", "四瓶", or {"count":4}' in user_message
    recovery_instruction = user_message.split("Input context:", 1)[0]
    assert "敏感原文不应进入固定指令。" not in recovery_instruction


def test_state_change_quantity_validation_exposes_only_safe_rule_code() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                json.dumps(_state_change_batch_json(quantity_value="4"), ensure_ascii=False)
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, StateChangeProposalBatchV1)

    diagnostics = exc_info.value.diagnostics
    assert diagnostics["schema_error_rule_codes"] == [
        "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER"
    ]
    assert "4" not in str(diagnostics)
    assert "敏感" not in str(diagnostics)


def test_provider_recovery_rejects_disbelief_of_claim_and_recovers_world_fact() -> (
    None
):
    invalid_provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                json.dumps(_knowledge_state_batch_json(target_kind="CLAIM"), ensure_ascii=False)
            )
        ),
    )
    with pytest.raises(ProviderResponseError, match="failed schema validation") as exc_info:
        invalid_provider.structured_generate({}, KnowledgeStateProposalBatchV1)
    assert exc_info.value.diagnostics["expected_output_schema"] == "KnowledgeStateProposalBatchV1"
    assert exc_info.value.diagnostics["schema_error_rule_codes"] == [
        "BELIEF_ATTITUDE_REQUIRES_WORLD_FACT_OR_EVENT"
    ]

    client = FakeHttpClient(
        response=_chat_response(
            json.dumps(_knowledge_state_batch_json(target_kind="WORLD_FACT"), ensure_ascii=False)
        )
    )
    recovery_provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    recovered = recovery_provider.structured_generate(
        {
            "input_context": {
                "output_recovery": "schema_validation",
                "source_chunks": [{"chunk_id": "chunk-1", "text": "Synthetic source."}],
            }
        },
        KnowledgeStateProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert recovered.states[0].target.target_kind == "WORLD_FACT"
    assert "exactly one KnowledgeStateProposalBatchV1 JSON object" in user_message
    assert "states array" in user_message
    assert "may be empty" in user_message


def test_knowledge_state_schema_recovery_includes_safe_rule_codes_and_v11_shape() -> None:
    client = FakeHttpClient(
        response=_chat_response(
            json.dumps(_knowledge_state_batch_json(target_kind="WORLD_FACT"), ensure_ascii=False)
        )
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    provider.structured_generate(
        {
            "input_context": {
                "output_recovery": "schema_validation",
                "schema_error_rule_codes": ["TARGET_REFERENCE_MUST_STAY_UNRESOLVED"],
                "source_chunks": [{"chunk_id": "chunk-1", "text": "Synthetic source."}],
            }
        },
        KnowledgeStateProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert "TARGET_REFERENCE_MUST_STAY_UNRESOLVED" in user_message
    assert '"schema_version":"1.1"' in user_message
    assert '"resolution_status":"UNRESOLVED"' in user_message
    assert '"proposal_id":null' in user_message


def test_relationship_signal_schema_recovery_includes_source_first_batch_shape() -> None:
    """A retry for the sixth Narrative Analyst mode must receive its own guidance."""

    client = FakeHttpClient(
        response=_chat_response(
            json.dumps(
                {"schema_version": "1.0", "batch_id": "relationship-batch-1", "signals": []},
                ensure_ascii=False,
            )
        )
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    recovered = provider.structured_generate(
        {
            "input_context": {
                "output_recovery": "schema_validation",
                "schema_error_rule_codes": [
                    "RELATIONSHIP_SIGNAL_SCHEMA_INVALID",
                    "RELATIONSHIP_SIGNAL_STATEMENT_SUPPORT_LEVEL_INVALID",
                ],
                "source_chunks": [{"chunk_id": "chunk-1", "text": "Synthetic source."}],
            }
        },
        RelationshipSignalProposalBatchV1,
    )

    user_message = client.requests[0]["json"]["messages"][1]["content"]
    assert recovered.signals == []
    assert "exactly one RelationshipSignalProposalBatchV1 JSON object" in user_message
    assert "signals array" in user_message
    assert "signals may be empty" in user_message
    assert '"resolution_status":"UNRESOLVED"' in user_message
    assert "RELATIONSHIP_SIGNAL_SCHEMA_INVALID" in user_message
    assert "traitor label is Claim-only" in user_message
    assert "DISTRUSTS plus FORMATION" in user_message
    assert "support_level=LIMITED" in user_message
    assert "never EXPLICIT" in user_message


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        (
            "relationship_domain does not match relationship_kind",
            "RELATIONSHIP_SIGNAL_DOMAIN_KIND_MISMATCH",
        ),
        (
            "statement evidence_basis requires source_speaker",
            "RELATIONSHIP_SIGNAL_STATEMENT_REQUIRES_SPEAKER",
        ),
        (
            "relationship change signal requires non-empty temporal anchor_text",
            "RELATIONSHIP_SIGNAL_CHANGE_REQUIRES_TEMPORAL_ANCHOR",
        ),
    ],
)
def test_relationship_signal_schema_rule_codes_are_safe_and_stable(
    message: str, expected_code: str
) -> None:
    assert (
        OpenAICompatibleLLMProvider._schema_validation_rule_code({"msg": message})
        == expected_code
    )


def test_openai_compatible_provider_extracts_markdown_wrapped_json() -> None:
    content = f"```json\n{json.dumps(_event_json(), ensure_ascii=False)}\n```"
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response(content)),
    )

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"


def test_openai_compatible_provider_extracts_json_after_a_short_preamble() -> None:
    content = f"Final structured result:\n{json.dumps(_event_json(), ensure_ascii=False)}"
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response(content)),
    )

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"


def test_openai_compatible_provider_rejects_non_json_content() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response("not json")),
    )

    with pytest.raises(ValueError, match="JSON"):
        provider.structured_generate({}, EventProposalV1)


def test_openai_compatible_provider_keeps_sanitized_diagnostics_for_invalid_json() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                "not json",
                finish_reason="stop",
                usage={"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider response did not contain valid JSON"
    assert exc_info.value.diagnostics["finish_reason"] == "stop"
    assert exc_info.value.diagnostics["content_type"] == "str"
    assert exc_info.value.diagnostics["content_length"] == 8
    assert exc_info.value.diagnostics["usage_total_tokens"] == 15


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (None, "LLM provider response content is missing"),
        ("", "LLM provider response content is missing"),
        ({"raw": "do-not-leak"}, "LLM provider response content has unsupported type: dict"),
    ],
)
def test_openai_compatible_provider_classifies_invalid_content_without_leaking_raw_response(
    content: Any,
    expected_message: str,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response(content)),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    message = str(exc_info.value)
    assert message == expected_message
    assert "secret-test-key" not in message
    assert "do-not-leak" not in message


def test_openai_compatible_provider_adds_sanitized_diagnostics_for_missing_content() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                None,
                finish_reason="stop",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 0,
                    "total_tokens": 11,
                },
                extra_message={"reasoning_content": "do-not-leak"},
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert exc_info.value.diagnostics == {
        "finish_reason": "stop",
        "response_has_choices": True,
        "choices_count": 1,
        "message_keys": ["content", "reasoning_content"],
        "content_type": "NoneType",
        "has_reasoning_content": True,
        "has_tool_calls": False,
        "usage_prompt_tokens": 11,
        "usage_completion_tokens": 0,
        "usage_total_tokens": 11,
    }
    serialized = json.dumps(exc_info.value.diagnostics, ensure_ascii=False)
    assert "secret-test-key" not in serialized
    assert "do-not-leak" not in serialized


def test_openai_compatible_provider_adds_sanitized_diagnostics_for_object_content() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                {"raw": "do-not-leak"},
                finish_reason="stop",
                extra_message={"tool_calls": [{"arguments": "do-not-leak"}]},
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider response content has unsupported type: dict"
    assert exc_info.value.diagnostics["content_type"] == "dict"
    assert exc_info.value.diagnostics["has_tool_calls"] is True
    assert "content_length" not in exc_info.value.diagnostics
    serialized = json.dumps(exc_info.value.diagnostics, ensure_ascii=False)
    assert "secret-test-key" not in serialized
    assert "do-not-leak" not in serialized


def test_openai_compatible_provider_adds_sanitized_diagnostics_for_empty_content() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response("", finish_reason="stop")),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider response content is missing"
    assert exc_info.value.diagnostics["content_type"] == "str"
    assert exc_info.value.diagnostics["content_length"] == 0


def test_openai_compatible_provider_classifies_length_finish_as_max_output_exceeded() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response("", finish_reason="length")),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == (
        "LLM provider response exceeded max output tokens before final content"
    )
    assert exc_info.value.diagnostics["finish_reason"] == "length"
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_rejects_schema_invalid_json() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response('{"proposal_id": "bad"}')),
    )

    with pytest.raises(ValueError, match="schema"):
        provider.structured_generate({}, EventProposalV1)


def test_openai_compatible_provider_adds_sanitized_diagnostics_for_schema_failure() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                '{"proposal_id": "bad"}',
                finish_reason="stop",
                usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider response failed schema validation"
    assert exc_info.value.diagnostics == {
        "finish_reason": "stop",
        "response_has_choices": True,
        "choices_count": 1,
        "message_keys": ["content"],
        "content_type": "str",
        "content_length": len('{"proposal_id": "bad"}'),
        "has_reasoning_content": False,
        "has_tool_calls": False,
        "usage_prompt_tokens": 5,
        "usage_completion_tokens": 4,
        "usage_total_tokens": 9,
        "schema_error_kind": "missing",
        "schema_error_field_paths": [
            "confidence",
            "event_type",
            "evidence_refs",
            "reality_layer",
            "summary",
        ],
        "expected_output_schema": "EventProposalV1",
    }


@pytest.mark.parametrize(
    ("output_model", "batch_field"),
    [
        (EntityProposalBatchV1, "entities"),
        (ClaimProposalBatchV1, "claims"),
    ],
)
def test_openai_compatible_provider_schema_failure_reports_batch_field_paths_only(
    output_model: type[EventProposalBatchV1 | EntityProposalBatchV1 | ClaimProposalBatchV1],
    batch_field: str,
) -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                json.dumps({"batch_id": "bad", batch_field: []}),
                finish_reason="stop",
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.structured_generate({}, output_model)

    diagnostics = exc_info.value.diagnostics
    serialized = json.dumps(diagnostics, ensure_ascii=False)
    assert diagnostics["schema_error_kind"] == "too_short"
    assert diagnostics["schema_error_field_paths"] == [batch_field]
    assert diagnostics["expected_output_schema"] == output_model.__name__
    assert "batch_id" not in serialized
    assert "secret-test-key" not in serialized


def test_openai_compatible_provider_accepts_empty_event_batch_for_a_bounded_scope() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(
            response=_chat_response(
                json.dumps({"batch_id": "empty-event-scope", "events": []}),
                finish_reason="stop",
            )
        ),
    )

    proposal = provider.structured_generate({}, EventProposalBatchV1)

    assert proposal.events == []


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
def test_openai_compatible_provider_http_error_does_not_leak_key(status_code: int) -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=FakeResponse(status_code, {})),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert "HTTP" in str(exc_info.value)
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_retries_one_transient_http_response() -> None:
    client = SequenceHttpClient(
        [
            FakeResponse(503, {}),
            _chat_response(json.dumps(_event_json(), ensure_ascii=False)),
        ]
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"
    assert len(client.requests) == 2


def test_openai_compatible_provider_retries_one_rate_limit_response() -> None:
    client = SequenceHttpClient(
        [
            FakeResponse(429, {}),
            _chat_response(json.dumps(_event_json(), ensure_ascii=False)),
        ]
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"
    assert len(client.requests) == 2


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_openai_compatible_provider_does_not_retry_nontransient_http_errors(
    status_code: int,
) -> None:
    client = SequenceHttpClient(
        [
            FakeResponse(status_code, {}),
            _chat_response(json.dumps(_event_json(), ensure_ascii=False)),
        ]
    )
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    with pytest.raises(ProviderHttpError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert exc_info.value.diagnostics == {
        "http_status_code": status_code,
        "request_attempts": 1,
    }
    assert len(client.requests) == 1


def test_openai_compatible_provider_keeps_final_http_diagnostics_sanitized() -> None:
    client = SequenceHttpClient([FakeResponse(429, {}), FakeResponse(429, {})])
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    with pytest.raises(ProviderHttpError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert exc_info.value.diagnostics == {"http_status_code": 429, "request_attempts": 2}
    assert "secret-test-key" not in str(exc_info.value)
    assert len(client.requests) == 2


def test_openai_compatible_provider_timeout_does_not_leak_key() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(exc=httpx.TimeoutException("timed out")),
    )

    with pytest.raises(TimeoutError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_retries_one_transient_timeout() -> None:
    client = SequenceHttpClient(
        [
            httpx.ReadTimeout("timed out"),
            _chat_response(json.dumps(_event_json(), ensure_ascii=False)),
        ]
    )
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        timeout_seconds=123,
        http_client=client,
    )

    proposal = provider.structured_generate({}, EventProposalV1)

    assert proposal.proposal_id == "proposal-1"
    assert len(client.requests) == 2
    assert {request["timeout"] for request in client.requests} == {123}


def test_openai_compatible_provider_reports_exhausted_timeout_diagnostics() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        timeout_seconds=123,
        http_client=SequenceHttpClient(
            [httpx.ReadTimeout("timed out"), httpx.ReadTimeout("timed out")]
        ),
    )

    with pytest.raises(ProviderTimeoutError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider read timeout after 2 attempts"
    assert exc_info.value.diagnostics == {
        "timeout_kind": "read",
        "timeout_seconds": 123,
        "request_attempts": 2,
    }
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_dns_error_is_classified_without_key() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=RaisingHttpClient(
            httpx.ConnectError("connect failed"),
            socket.gaierror("mock dns failure"),
        ),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider DNS resolution failed"
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_tls_error_is_classified_without_key() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=RaisingHttpClient(
            httpx.ConnectError("connect failed"),
            ssl.SSLError("certificate verify failed"),
        ),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider TLS handshake failed"
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_connection_refused_is_classified_without_key() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=RaisingHttpClient(
            httpx.ConnectError("connect failed"),
            ConnectionRefusedError("connection refused"),
        ),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider connection refused"
    assert "secret-test-key" not in str(exc_info.value)


def test_openai_compatible_provider_network_error_is_classified_without_key() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=RaisingHttpClient(httpx.NetworkError("network unavailable")),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.structured_generate({}, EventProposalV1)

    assert str(exc_info.value) == "LLM provider network error"
    assert "secret-test-key" not in str(exc_info.value)
