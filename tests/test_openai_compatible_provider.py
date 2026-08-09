import json
import os
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, ValidationError

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
        api_key="test-api-key",
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
        api_key="test-api-key",
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
    assert settings.llm_api_key == "test-api-key"
    assert settings.storybible_model == "deepseek-v4-pro"
    assert settings.llm_timeout_seconds == 60.0


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
