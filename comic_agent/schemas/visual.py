"""Visual planning schemas that stay provider-neutral."""

from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


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
