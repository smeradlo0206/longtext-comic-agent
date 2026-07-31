"""OpenAI-compatible structured LLM provider."""

import json
import re
import socket
import ssl
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)
ProviderDiagnostics = dict[str, object]


class ProviderResponseError(ValueError):
    """Sanitized provider response parsing error with non-secret diagnostics."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


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
        response_format: str | None = None,
        timeout_seconds: int = 60,
        max_output_tokens: int = 2000,
        http_client: HttpClient | None = None,
    ) -> None:
        if api_key is None or api_key.strip() == "":
            raise ValueError("LLM API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._response_format = response_format.strip() if response_format else None
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
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": self._messages(request, output_model),
                "temperature": 0,
                "max_tokens": self._max_output_tokens,
            }
            if self._response_format == "json_object":
                payload["response_format"] = {"type": "json_object"}

            response = self._http_client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                json=payload,
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
            response_payload = response.json()
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM provider response format is invalid") from exc
        diagnostics = self._response_diagnostics(response_payload)
        self._validate_response_content(content, diagnostics)

        try:
            payload = json.loads(self._extract_json(content))
        except json.JSONDecodeError as exc:
            if self._exceeded_max_output_tokens(diagnostics):
                raise ProviderResponseError(
                    self._max_output_tokens_error_message(),
                    diagnostics=diagnostics,
                ) from exc
            raise ValueError("LLM provider response did not contain valid JSON") from exc

        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            raise ProviderResponseError(
                (
                    self._max_output_tokens_error_message()
                    if self._exceeded_max_output_tokens(diagnostics)
                    else "LLM provider response failed schema validation"
                ),
                diagnostics=diagnostics,
            ) from exc

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

    def _validate_response_content(
        self,
        content: Any,
        diagnostics: ProviderDiagnostics,
    ) -> None:
        if self._exceeded_max_output_tokens(diagnostics):
            raise ProviderResponseError(
                self._max_output_tokens_error_message(),
                diagnostics=diagnostics,
            )
        if content is None:
            raise ProviderResponseError(
                "LLM provider response content is missing",
                diagnostics=diagnostics,
            )
        if not isinstance(content, str):
            type_name = type(content).__name__
            raise ProviderResponseError(
                f"LLM provider response content has unsupported type: {type_name}",
                diagnostics=diagnostics,
            )
        if content.strip() == "":
            raise ProviderResponseError(
                "LLM provider response content is missing",
                diagnostics=diagnostics,
            )

    def _response_diagnostics(self, response_payload: Any) -> ProviderDiagnostics:
        choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
        choices_list = choices if isinstance(choices, list) else []
        first_choice = choices_list[0] if choices_list else None
        first_choice_dict = first_choice if isinstance(first_choice, dict) else {}
        message = first_choice_dict.get("message")
        message_dict = message if isinstance(message, dict) else {}
        content = message_dict.get("content")
        usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
        usage_dict = usage if isinstance(usage, dict) else {}

        diagnostics: ProviderDiagnostics = {
            "finish_reason": (
                first_choice_dict.get("finish_reason")
                if isinstance(first_choice_dict.get("finish_reason"), str)
                else None
            ),
            "response_has_choices": bool(choices_list),
            "choices_count": len(choices_list),
            "message_keys": sorted(str(key) for key in message_dict),
            "content_type": type(content).__name__,
            "has_reasoning_content": "reasoning_content" in message_dict,
            "has_tool_calls": bool(message_dict.get("tool_calls")),
        }
        if isinstance(content, str):
            diagnostics["content_length"] = len(content)

        token_fields = {
            "prompt_tokens": "usage_prompt_tokens",
            "completion_tokens": "usage_completion_tokens",
            "total_tokens": "usage_total_tokens",
        }
        for source_key, diagnostic_key in token_fields.items():
            token_value = usage_dict.get(source_key)
            if isinstance(token_value, int):
                diagnostics[diagnostic_key] = token_value

        return diagnostics

    def _exceeded_max_output_tokens(self, diagnostics: ProviderDiagnostics) -> bool:
        return diagnostics.get("finish_reason") == "length"

    def _max_output_tokens_error_message(self) -> str:
        return "LLM provider response exceeded max output tokens before final content"

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
