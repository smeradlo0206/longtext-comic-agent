"""Deterministic scene and panel planning contracts for downstream image generation."""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class ComicPlanningInputV1(StrictBaseModel):
    """Trusted frozen bundle identifiers accepted by Comic Planning."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    storybible_bundle_id: str
    timeline_bundle_id: str

    @field_validator("project_id", "storybible_bundle_id", "timeline_bundle_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _non_blank(value)


class ScenePlanV1(StrictBaseModel):
    """Evidence-grounded narrative unit derived from approved Timeline events."""

    schema_version: Literal["1.0"] = "1.0"
    scene_id: str
    project_id: str
    storybible_bundle_id: str
    timeline_bundle_id: str
    title: str
    summary: str
    purpose: str
    related_event_ids: list[str] = Field(min_length=1)
    character_ids: list[str] = Field(default_factory=list)
    location: str | None = None
    time: str | None = None
    emotion: str | None = None
    continuity_notes: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator(
        "scene_id",
        "project_id",
        "storybible_bundle_id",
        "timeline_bundle_id",
        "title",
        "summary",
        "purpose",
    )
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("location", "time", "emotion")
    @classmethod
    def optional_text_is_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _non_blank(value)

    @model_validator(mode="after")
    def references_are_unique(self) -> "ScenePlanV1":
        if len(self.related_event_ids) != len(set(self.related_event_ids)):
            raise ValueError("related_event_ids must be unique")
        if len(self.character_ids) != len(set(self.character_ids)):
            raise ValueError("character_ids must be unique")
        return self


class PanelPlanV1(StrictBaseModel):
    """Image-agent-ready panel specification without image model parameters."""

    schema_version: Literal["1.0"] = "1.0"
    panel_id: str
    project_id: str
    scene_id: str
    index: int = Field(ge=0)
    storybible_bundle_id: str
    timeline_bundle_id: str
    panel_purpose: str
    narrative_beat: str
    aspect_ratio: str

    shot_type: str
    camera_angle: str
    composition: str

    character_ids: list[str] = Field(default_factory=list)
    character_state_ids: list[str] = Field(default_factory=list)
    character_actions: dict[str, str] = Field(default_factory=dict)
    expressions: dict[str, str] = Field(default_factory=dict)

    background: str | None = None
    location_entity_id: str | None = None
    objects: list[str] = Field(default_factory=list)
    atmosphere: str | None = None

    dialogue: list[str] = Field(default_factory=list)
    narration: str | None = None
    caption: str | None = None

    previous_panel_reference: str | None = None
    continuity_notes: list[str] = Field(default_factory=list)
    related_event_ids: list[str] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator(
        "panel_id",
        "project_id",
        "scene_id",
        "storybible_bundle_id",
        "timeline_bundle_id",
        "panel_purpose",
        "narrative_beat",
        "aspect_ratio",
        "shot_type",
        "camera_angle",
        "composition",
    )
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator(
        "background",
        "location_entity_id",
        "atmosphere",
        "narration",
        "caption",
        "previous_panel_reference",
    )
    @classmethod
    def optional_text_is_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _non_blank(value)

    @field_validator("aspect_ratio")
    @classmethod
    def aspect_ratio_is_valid(cls, value: str) -> str:
        if re.fullmatch(r"[1-9]\d*(?:\.\d+)?:[1-9]\d*(?:\.\d+)?", value) is None:
            raise ValueError("aspect_ratio must use a positive width:height format")
        return value

    @field_validator("character_actions", "expressions")
    @classmethod
    def character_values_are_not_blank(cls, value: dict[str, str]) -> dict[str, str]:
        return {_non_blank(key): _non_blank(item) for key, item in value.items()}

    @model_validator(mode="after")
    def validate_panel_references(self) -> "PanelPlanV1":
        if len(self.character_ids) != len(set(self.character_ids)):
            raise ValueError("character_ids must be unique")
        if len(self.related_event_ids) != len(set(self.related_event_ids)):
            raise ValueError("related_event_ids must be unique")
        if len(self.character_state_ids) != len(set(self.character_state_ids)):
            raise ValueError("character_state_ids must be unique")
        character_ids = set(self.character_ids)
        if not set(self.character_actions).issubset(character_ids):
            raise ValueError("character_actions keys must reference panel characters")
        if not set(self.expressions).issubset(character_ids):
            raise ValueError("expressions keys must reference panel characters")
        return self
