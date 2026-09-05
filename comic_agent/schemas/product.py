"""Browser input for the extractive comic production entrypoint."""

from typing import Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class ProductGenerationRequestV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1, max_length=5000)
    style: str = Field(min_length=1, max_length=100)
    aspect_ratio: Literal["portrait", "landscape", "square"] = "portrait"
    max_pages: int = Field(default=12, ge=1, le=20)
