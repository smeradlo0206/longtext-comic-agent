import json
import os
import socket
import ssl
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from comic_agent.config import Settings
from comic_agent.providers.openai_compatible import OpenAICompatibleProvider


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
from typing import Any

import httpx
import pytest

from comic_agent.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalBatchV1, EventProposalV1


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


def test_openai_compatible_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenAICompatibleLLMProvider(api_key=None)


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


def test_openai_compatible_provider_omits_response_format_by_default() -> None:
    client = FakeHttpClient(response=_chat_response(json.dumps(_event_json(), ensure_ascii=False)))
    provider = OpenAICompatibleLLMProvider(api_key="secret-test-key", http_client=client)

    provider.structured_generate({}, EventProposalV1)

    assert "response_format" not in client.requests[0]["json"]


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
    }


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
