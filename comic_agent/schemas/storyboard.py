"""Scene and story beat schemas."""

from typing import Literal

from pydantic import Field

from comic_agent.schemas.base import RealityLayer, StrictBaseModel


class SceneSpecV1(StrictBaseModel):
    """Source-grounded scene boundary for narrative translation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    scene_id: str = Field(description="Scene id.")
    chapter_id: str = Field(description="Source chapter id.")
    source_chunk_ids: list[str] = Field(description="Source chunks in scene.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    story_time_ref: str | None = Field(default=None, description="Story time reference.")
    location_id: str | None = Field(default=None, description="Location entity id.")
    character_ids: list[str] = Field(default_factory=list, description="Characters present.")
    scene_purpose: str = Field(description="Scene function in the source story.")


class StoryBeatV1(StrictBaseModel):
    """Panel/page planning unit derived from a scene."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    beat_id: str = Field(description="Story beat id.")
    scene_id: str = Field(description="Parent scene id.")
    source_chunk_ids: list[str] = Field(description="Source chunks supporting this beat.")
    meaning: str = Field(description="Narrative meaning that must survive adaptation.")
    visual_expression: str = Field(description="Suggested visual expression.")
    dialogue_ids: list[str] = Field(default_factory=list, description="Dialogue references.")
    narration_ids: list[str] = Field(default_factory=list, description="Narration references.")
    new_story_information: bool = Field(
        default=False,
        description="Whether this beat introduces story information not in source.",
    )
