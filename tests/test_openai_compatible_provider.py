import json
import os
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

from comic_agent.providers.openai_compatible import OpenAICompatibleLLMProvider
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1


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


def _chat_response(content: str) -> FakeResponse:
    return FakeResponse(
        200,
        {"choices": [{"message": {"content": content}}]},
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


def test_openai_compatible_provider_extracts_markdown_wrapped_json() -> None:
    content = f"```json\n{json.dumps(_event_json(), ensure_ascii=False)}\n```"
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


def test_openai_compatible_provider_rejects_schema_invalid_json() -> None:
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-test-key",
        http_client=FakeHttpClient(response=_chat_response('{"proposal_id": "bad"}')),
    )

    with pytest.raises(ValueError, match="schema"):
        provider.structured_generate({}, EventProposalV1)


@pytest.mark.parametrize("status_code", [401, 500])
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
