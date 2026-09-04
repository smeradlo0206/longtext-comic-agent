"""Visual planning schemas that stay provider-neutral."""

from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class PanelTextOverlayV1(StrictBaseModel):
    """Source-grounded dialogue or caption rendered after image generation."""

    schema_version: Literal["1.0"] = "1.0"
    overlay_id: str
    kind: Literal["dialogue", "caption"]
    text: str = Field(min_length=1, max_length=500)
    speaker_entity_id: str | None = None
    source_quote_start: int = Field(ge=0)
    source_quote_end: int = Field(gt=0)
    preferred_region: Literal["top_left", "top_right", "bottom_left", "bottom_right"]

    def model_post_init(self, __context: Any) -> None:
        if self.source_quote_end <= self.source_quote_start:
            raise ValueError("text overlay source range must be non-empty")


class PageSpecV1(StrictBaseModel):
    """Provider-neutral page grouping for ordered comic panels."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    page_id: str = Field(description="Page id.")
    project_id: str = Field(description="Owning project id.")
    document_id: str = Field(description="Source document id.")
    chapter_ids: list[str] = Field(description="Source chapters represented on the page.")
    source_chunk_ids: list[str] = Field(description="Source chunks represented on the page.")
    order: int = Field(ge=0, description="Zero-based page order.")
    panel_ids: list[str] = Field(min_length=1, max_length=6, description="Panels in reading order.")
    reading_direction: str = Field(description="Reading direction inherited from the project.")
    layout: str = Field(default="2x3", description="Provider-neutral page layout label.")


class PanelSpecV1(StrictBaseModel):
    """Provider-neutral description of one comic panel."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    panel_id: str = Field(description="Panel id.")
    page_id: str = Field(description="Page id.")
    scene_id: str = Field(description="Scene id.")
    source_chunk_ids: list[str] = Field(description="Source chunks supporting this panel.")
    story_time_ref: str | None = Field(default=None, description="Story time reference.")
    character_bindings: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping from role names to character/variant ids.",
    )
    shot_type: str = Field(description="Shot type, e.g. close-up or wide.")
    camera_angle: str = Field(description="Camera angle.")
    must_show: list[str] = Field(default_factory=list, description="Required visual facts.")
    must_not_show: list[str] = Field(default_factory=list, description="Forbidden visual facts.")
    reserved_text_regions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Provider-neutral text-safe layout regions.",
    )
    text_overlays: list[PanelTextOverlayV1] = Field(
        default_factory=list,
        max_length=8,
        description="Source-grounded dialogue and captions for post-generation lettering.",
    )
