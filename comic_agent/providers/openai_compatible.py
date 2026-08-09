"""OpenAI-compatible structured-generation provider."""

from typing import cast

import httpx

from comic_agent.providers.llm import OutputModelT


class OpenAICompatibleProvider:
    """Generate validated JSON through an OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
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
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Post a JSON-object request and validate the first assistant message."""

        payload = dict(request)
        payload["model"] = self._model
        payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()

        content = self._message_content(response.json())
        return output_model.model_validate_json(content)

    @staticmethod
    def _message_content(response_payload: object) -> str:
        if not isinstance(response_payload, dict):
            raise ValueError("provider response must be a JSON object")
        response_object = cast(dict[str, object], response_payload)
        choices = response_object.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("provider response must contain at least one choice")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("provider choice must be a JSON object")
        choice_object = cast(dict[str, object], first_choice)
        message = choice_object.get("message")
        if not isinstance(message, dict):
            raise ValueError("provider choice must contain a message object")
        message_object = cast(dict[str, object], message)
        content = message_object.get("content")
        if not isinstance(content, str):
            raise ValueError("provider message content must be a JSON string")
        return content
