"""OpenAI-compatible structured-generation provider."""

import json
import re
import socket
import ssl
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from comic_agent.providers.llm import OutputModelT as ProviderOutputModelT


class OpenAICompatibleProvider:
    """Generate validated JSON through an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float = 60,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[ProviderOutputModelT],
    ) -> ProviderOutputModelT:
        """Post a JSON-object request and validate the first assistant message."""

        payload = dict(request)
        payload["model"] = self._model
        payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
            response = client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()
        return output_model.model_validate_json(self._message_content(response.json()))

    @staticmethod
    def _message_content(response_payload: object) -> str:
        if not isinstance(response_payload, dict):
            raise ValueError("provider response must be a JSON object")
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider response must contain at least one choice")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("provider choice must be a JSON object")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("provider choice must contain a message object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("provider message content must be a JSON string")
        return content

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class HttpClient(Protocol):
    """HTTP client surface used by OpenAICompatibleLLMProvider."""

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> httpx.Response:
        """POST JSON data to an HTTP endpoint."""


class OpenAICompatibleLLMProvider:
    """Structured provider for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.llm.ustc.edu.cn/v1",
        model: str = "deepseek-v4-pro",
        timeout_seconds: int = 60,
        max_output_tokens: int = 2000,
        http_client: HttpClient | None = None,
    ) -> None:
        if api_key is None or api_key.strip() == "":
            raise ValueError("LLM API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._http_client = http_client or httpx.Client()

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Generate and validate one structured Pydantic model."""

        try:
            response = self._http_client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json={
                    "model": self._model,
                    "messages": self._messages(request, output_model),
                    "temperature": 0,
                    "max_tokens": self._max_output_tokens,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TimeoutError("LLM provider timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError(self._classify_http_status_error(exc.response.status_code)) from exc
        except httpx.ConnectError as exc:
            raise ValueError(self._classify_connect_error(exc)) from exc
        except httpx.NetworkError as exc:
            raise ValueError("LLM provider network error") from exc
        except httpx.HTTPError as exc:
            raise ValueError("LLM provider request error") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM provider response format is invalid") from exc
        if not isinstance(content, str):
            raise ValueError("LLM provider response content is invalid")

        try:
            payload = json.loads(self._extract_json(content))
        except json.JSONDecodeError as exc:
            raise ValueError("LLM provider response did not contain valid JSON") from exc

        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("LLM provider response failed schema validation") from exc

    def _messages(
        self,
        request: dict[str, object],
        output_model: type[BaseModel],
    ) -> list[dict[str, str]]:
        system_prompt = str(
            request.get(
                "system_prompt",
                "You are a strict extraction model. Return JSON only.",
            )
        )
        user_prompt = str(request.get("user_prompt", "Extract one structured object."))
        input_context = request.get("input_context", {})
        schema_name = output_model.__name__
        schema_json = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
        context_json = json.dumps(input_context, ensure_ascii=False, sort_keys=True)
        return [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n"
                    "Return only valid JSON. Do not return markdown or explanations."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    f"Output schema: {schema_name}\n"
                    f"JSON Schema: {schema_json}\n"
                    f"Input context: {context_json}"
                ),
            },
        ]

    def _extract_json(self, content: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        return content.strip()

    def _classify_http_status_error(self, status_code: int) -> str:
        if status_code in {401, 403}:
            reason = "authentication or authorization failed"
        elif status_code == 404:
            reason = "endpoint or model not found"
        elif status_code == 429:
            reason = "rate limited"
        elif status_code == 400:
            reason = "bad request"
        elif status_code >= 500:
            reason = "provider server error"
        else:
            reason = "request rejected"
        return f"LLM provider HTTP error: {status_code} ({reason})"

    def _classify_connect_error(self, exc: httpx.ConnectError) -> str:
        for cause in self._iter_exception_causes(exc):
            if isinstance(cause, socket.gaierror):
                return "LLM provider DNS resolution failed"
            if isinstance(cause, ssl.SSLError):
                return "LLM provider TLS handshake failed"
            if isinstance(cause, ConnectionRefusedError):
                return "LLM provider connection refused"

        message = str(exc).lower()
        if any(token in message for token in ("dns", "getaddrinfo", "name or service")):
            return "LLM provider DNS resolution failed"
        if any(token in message for token in ("ssl", "tls", "certificate")):
            return "LLM provider TLS handshake failed"
        if "refused" in message:
            return "LLM provider connection refused"
        return "LLM provider connection failed"

    def _iter_exception_causes(self, exc: BaseException) -> list[BaseException]:
        causes: list[BaseException] = []
        current = exc.__cause__
        while current is not None:
            causes.append(current)
            current = current.__cause__
        return causes
