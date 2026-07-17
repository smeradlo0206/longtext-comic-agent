"""Image provider protocol."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ImageResult:
    """Result of image generation or edit."""

    storage_uri: str
    width: int
    height: int
    metadata: dict[str, object]


class ImageProvider(Protocol):
    """Provider-neutral image generation interface."""

    def generate(self, request: dict[str, object]) -> ImageResult:
        """Generate an image from provider-neutral request data."""

    def edit(self, request: dict[str, object]) -> ImageResult:
        """Edit an existing image from provider-neutral request data."""
