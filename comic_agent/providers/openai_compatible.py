"""OpenAI-compatible structured LLM provider."""

import json
import re
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

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
            status_code = exc.response.status_code
            raise ValueError(f"LLM provider HTTP error: {status_code}") from exc
        except httpx.HTTPError as exc:
            raise ValueError("LLM provider HTTP request failed") from exc

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
