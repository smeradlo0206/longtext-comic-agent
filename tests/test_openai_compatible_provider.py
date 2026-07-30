import json
import socket
import ssl
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
