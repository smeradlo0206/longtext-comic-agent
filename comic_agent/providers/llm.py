"""LLM provider protocol."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class LLMProvider(Protocol):
    """Structured generation provider interface."""

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        """Generate a structured Pydantic model without exposing raw provider details."""
