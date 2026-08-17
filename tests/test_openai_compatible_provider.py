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


def test_openai_provider_retries_one_http_failure_when_configured() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
            request=request,
        )

    provider = OpenAICompatibleProvider(
        base_url="https://api.example/v1",
        api_key=SecretStr("test-api-key"),
        model="deepseek-v4-pro",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    assert provider.structured_generate({"messages": []}, OutputModel) == OutputModel(answer="ok")
    assert attempts == 2


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
    assert settings.timeline_llm_enabled is False
    assert settings.timeline_llm_max_retries == 1


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
