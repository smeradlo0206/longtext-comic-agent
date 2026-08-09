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
ProviderDiagnostics = dict[str, object]
MAX_TIMEOUT_ATTEMPTS = 2


class ProviderResponseError(ValueError):
    """Sanitized provider response parsing error with non-secret diagnostics."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ProviderHttpError(ValueError):
    """Sanitized HTTP provider error with status-only diagnostics."""

    def __init__(self, message: str, diagnostics: ProviderDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ProviderTimeoutError(TimeoutError):
    """Sanitized timeout error that records only request-level metadata."""

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

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(request, output_model),
            "temperature": 0,
            "max_tokens": self._max_output_tokens,
        }
        if self._response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            response, request_attempts = self._post_with_one_timeout_retry(payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderHttpError(
                self._classify_http_status_error(exc.response.status_code),
                diagnostics={
                    "http_status_code": exc.response.status_code,
                    "request_attempts": request_attempts,
                },
            ) from exc
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
            raise ProviderResponseError(
                "LLM provider response did not contain valid JSON",
                diagnostics=diagnostics,
            ) from exc

        try:
            return output_model.model_validate(payload)
        except ValidationError as exc:
            diagnostics.update(self._schema_validation_diagnostics(exc, output_model))
            raise ProviderResponseError(
                (
                    self._max_output_tokens_error_message()
                    if self._exceeded_max_output_tokens(diagnostics)
                    else "LLM provider response failed schema validation"
                ),
                diagnostics=diagnostics,
            ) from exc

    def _schema_validation_diagnostics(
        self,
        exc: ValidationError,
        output_model: type[BaseModel],
    ) -> ProviderDiagnostics:
        """Return schema-only Pydantic metadata without invalid values or response content."""

        field_paths: list[str] = []
        error_kinds: list[str] = []
        for error in exc.errors(include_input=False):
            error_type = error.get("type")
            if isinstance(error_type, str):
                error_kinds.append(error_type)
            location = error.get("loc")
            if not isinstance(location, tuple):
                continue
            path_parts = [str(item) for item in location if isinstance(item, (str, int))]
            if path_parts:
                field_paths.append(".".join(path_parts))
        unique_kinds = sorted(set(error_kinds))
        return {
            "schema_error_kind": unique_kinds[0] if len(unique_kinds) == 1 else "multiple",
            "schema_error_field_paths": sorted(set(field_paths)),
            "expected_output_schema": output_model.__name__,
        }

    def _post_with_one_timeout_retry(self, payload: dict[str, Any]) -> tuple[httpx.Response, int]:
        """Retry one timeout or transient HTTP response without exposing its body."""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        for request_attempt in range(1, MAX_TIMEOUT_ATTEMPTS + 1):
            try:
                response = self._http_client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
                if self._is_retryable_http_status(response.status_code):
                    if request_attempt < MAX_TIMEOUT_ATTEMPTS:
                        continue
                return response, request_attempt
            except httpx.TimeoutException as exc:
                if request_attempt == MAX_TIMEOUT_ATTEMPTS:
                    timeout_kind = self._timeout_kind(exc)
                    raise ProviderTimeoutError(
                        (f"LLM provider {timeout_kind} timeout after {request_attempt} attempts"),
                        diagnostics={
                            "timeout_kind": timeout_kind,
                            "timeout_seconds": self._timeout_seconds,
                            "request_attempts": request_attempt,
                        },
                    ) from exc
        raise AssertionError("timeout retry loop exited unexpectedly")

    def _is_retryable_http_status(self, status_code: int) -> bool:
        """Retry temporary capacity responses once, never auth or malformed requests."""

        return status_code == 429 or status_code >= 500

    def _timeout_kind(self, exc: httpx.TimeoutException) -> str:
        """Return a safe, phase-level timeout label without provider details."""

        if isinstance(exc, httpx.ConnectTimeout):
            return "connect"
        if isinstance(exc, httpx.ReadTimeout):
            return "read"
        if isinstance(exc, httpx.WriteTimeout):
            return "write"
        if isinstance(exc, httpx.PoolTimeout):
            return "pool"
        return "request"

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
        output_contract = self._compact_output_contract(output_model)
        schema_json = json.dumps(output_contract, ensure_ascii=False, separators=(",", ":"))
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
                    f"Output contract: {schema_json}\n"
                    f"{self._format_recovery_instruction(input_context, schema_name)}"
                    f"Input context: {context_json}"
                ),
            },
        ]

    def _format_recovery_instruction(self, input_context: object, schema_name: str) -> str:
        """Return a fixed, source-free correction instruction for one schema retry."""

        if not isinstance(input_context, dict):
            return ""
        if input_context.get("output_recovery") != "schema_validation":
            return ""
        batch_field = {
            "EventProposalBatchV1": "events",
            "EntityProposalBatchV1": "entities",
            "ClaimProposalBatchV1": "claims",
        }.get(schema_name)
        if batch_field is None:
            return ""
        return (
            "Format recovery instruction: Return exactly one "
            f"{schema_name} JSON object. Return no markdown, explanation, reasoning, or alternate "
            f"schema. Include a non-empty {batch_field} array and every required field.\n\n"
        )

    def _compact_output_contract(self, output_model: type[BaseModel]) -> dict[str, object]:
        """Return a small, reference-free schema guide derived from Pydantic."""

        schema = output_model.model_json_schema()
        definitions = schema.get("$defs")
        definition_map = definitions if isinstance(definitions, dict) else {}
        contract = self._compact_schema_node(schema, definition_map, set())
        return contract if isinstance(contract, dict) else {"type": "object"}

    def _compact_schema_node(
        self,
        node: object,
        definitions: dict[str, object],
        resolving_refs: set[str],
    ) -> object:
        """Keep only generation-relevant JSON Schema fields and inline local refs."""

        if not isinstance(node, dict):
            return node

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition_name = reference.removeprefix("#/$defs/")
            if definition_name in resolving_refs:
                return {"type": "object"}
            definition = definitions.get(definition_name)
            return self._compact_schema_node(
                definition,
                definitions,
                resolving_refs | {definition_name},
            )

        compact: dict[str, object] = {}
        for key in ("type", "enum", "const"):
            value = node.get(key)
            if value is not None:
                compact[key] = value

        required = node.get("required")
        if isinstance(required, list):
            compact["required"] = [item for item in required if isinstance(item, str)]

        properties = node.get("properties")
        if isinstance(properties, dict):
            compact["properties"] = {
                str(name): self._compact_schema_node(value, definitions, resolving_refs)
                for name, value in properties.items()
            }

        items = node.get("items")
        if isinstance(items, dict):
            compact["items"] = self._compact_schema_node(items, definitions, resolving_refs)

        for key in ("anyOf", "oneOf"):
            variants = node.get(key)
            if isinstance(variants, list):
                compact[key] = [
                    self._compact_schema_node(variant, definitions, resolving_refs)
                    for variant in variants
                ]

        return compact

    def _extract_json(self, content: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()

        stripped = content.strip()
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", stripped):
            candidate = stripped[match.start() :]
            try:
                _, end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            return candidate[:end].strip()
        return stripped

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
