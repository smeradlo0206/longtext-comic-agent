"""Predictable mock providers for unit tests."""

from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from comic_agent.providers.image import ImageResult

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class MockMode(StrEnum):
    """Mock provider behavior mode."""

    SUCCESS = "SUCCESS"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    TIMEOUT = "TIMEOUT"


class MockLLMProvider:
    """Network-free structured LLM mock."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        mode: MockMode = MockMode.SUCCESS,
    ) -> None:
        self._response = response or {}
        self._mode = mode

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Return configured structured data or deterministic errors."""

        if self._mode == MockMode.TIMEOUT:
            raise TimeoutError("mock provider timeout")
        if self._mode == MockMode.SCHEMA_ERROR:
            try:
                output_model.model_validate(self._response)
            except ValidationError as exc:
                raise ValueError("mock schema error") from exc
            raise ValueError("mock schema error")
        return output_model.model_validate(self._response)


class MockImageProvider:
    """Network-free image provider mock."""

    def generate(self, request: dict[str, object]) -> ImageResult:
        """Return a predictable mock image URI."""

        panel_id = str(request.get("panel_id", "image"))
        return ImageResult(
            storage_uri=f"mock://images/{panel_id}.png",
            width=1024,
            height=1024,
            metadata={"mode": "generate"},
        )

    def edit(self, request: dict[str, object]) -> ImageResult:
        """Return a predictable mock edit URI."""

        panel_id = str(request.get("panel_id", "image"))
        return ImageResult(
            storage_uri=f"mock://images/{panel_id}-edit.png",
            width=1024,
            height=1024,
            metadata={"mode": "edit"},
        )
