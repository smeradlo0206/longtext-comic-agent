from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .scene_contracts import (
    CharacterIntentV1,
    DialogueV1,
    Identifier,
    PanelIntentV1,
    RenderProfile,
    SceneContextV1,
    SceneJobV1,
    ShortText,
    StrictModel,
)


JsonScalar = str | int | float | bool | None


class UpstreamCharacterV1(StrictModel):
    character_id: Identifier
    name: ShortText
    appearance: ShortText
    clothing: list[ShortText] = Field(min_length=1, max_length=16)


class UpstreamSceneEntityV1(StrictModel):
    entity_id: Identifier
    name: ShortText
    description: ShortText


class UpstreamSceneV1(StrictModel):
    summary: ShortText
    location_id: Identifier
    location: ShortText
    time_of_day: ShortText | None = None
    atmosphere: ShortText | None = None
    entities: list[UpstreamSceneEntityV1] = Field(default_factory=list, max_length=128)

    @field_validator("entities")
    @classmethod
    def unique_entities(cls, value: list[UpstreamSceneEntityV1]) -> list[UpstreamSceneEntityV1]:
        _require_unique([item.entity_id for item in value], "entity_ids")
        return value


class UpstreamStateChangeV1(StrictModel):
    subject_id: Identifier
    path: ShortText
    before: JsonScalar
    after: JsonScalar

    @model_validator(mode="after")
    def value_must_change(self) -> "UpstreamStateChangeV1":
        if self.before == self.after and type(self.before) is type(self.after):
            raise ValueError("state change before and after values must differ")
        return self


class UpstreamEventV1(StrictModel):
    event_id: Identifier
    sequence_no: int = Field(ge=0)
    action: ShortText
    actor_ids: list[Identifier] = Field(min_length=1, max_length=2)
    target_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    cause_event_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    state_changes: list[UpstreamStateChangeV1] = Field(default_factory=list, max_length=32)

    @field_validator("actor_ids", "target_ids", "cause_event_ids")
    @classmethod
    def unique_references(cls, value: list[str]) -> list[str]:
        _require_unique(value, "event references")
        return value


class UpstreamPanelCharacterV1(StrictModel):
    character_id: Identifier
    action: ShortText
    emotion: ShortText


class UpstreamDialogueV1(StrictModel):
    dialogue_id: Identifier
    speaker_id: Identifier
    kind: Literal["speech", "thought", "off_screen"] = "speech"
    text: ShortText


class UpstreamPanelPlanV1(StrictModel):
    panel_id: Identifier
    sequence_no: int = Field(ge=0)
    event_ids: list[Identifier] = Field(min_length=1, max_length=16)
    story_intent: ShortText
    characters: list[UpstreamPanelCharacterV1] = Field(default_factory=list, max_length=2)
    dialogue: list[UpstreamDialogueV1] = Field(default_factory=list, max_length=16)
    constraints: list[ShortText] = Field(default_factory=list, max_length=32)
    movement_direction: Literal["left_to_right", "right_to_left", "toward_camera", "away_from_camera"] | None = None
    render_profile: RenderProfile = RenderProfile.LANDSCAPE

    @field_validator("event_ids")
    @classmethod
    def unique_events(cls, value: list[str]) -> list[str]:
        _require_unique(value, "panel event_ids")
        return value

    @field_validator("characters")
    @classmethod
    def unique_characters(cls, value: list[UpstreamPanelCharacterV1]) -> list[UpstreamPanelCharacterV1]:
        _require_unique([item.character_id for item in value], "panel character_ids")
        return value

    @field_validator("dialogue")
    @classmethod
    def unique_dialogue(cls, value: list[UpstreamDialogueV1]) -> list[UpstreamDialogueV1]:
        _require_unique([item.dialogue_id for item in value], "dialogue_ids")
        return value


class UpstreamSceneEnvelopeV1(StrictModel):
    schema_name: Literal["UpstreamSceneEnvelopeV1"] = "UpstreamSceneEnvelopeV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    project_id: Identifier
    chapter_id: Identifier
    scene_id: Identifier
    asset_profile_id: Identifier
    characters: list[UpstreamCharacterV1] = Field(min_length=1, max_length=128)
    scene: UpstreamSceneV1
    events: list[UpstreamEventV1] = Field(min_length=1, max_length=256)
    panels: list[UpstreamPanelPlanV1] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_graph(self) -> "UpstreamSceneEnvelopeV1":
        character_ids = [item.character_id for item in self.characters]
        _require_unique(character_ids, "character_ids")
        character_set = set(character_ids)
        entity_set = {item.entity_id for item in self.scene.entities}
        known_subjects = character_set | entity_set

        event_ids = [item.event_id for item in self.events]
        _require_unique(event_ids, "event_ids")
        _require_unique([item.sequence_no for item in self.events], "event sequence_no values")
        events = {item.event_id: item for item in self.events}
        for event in self.events:
            _require_known(event.actor_ids, character_set, f"event {event.event_id} actor")
            _require_known(event.target_ids, known_subjects, f"event {event.event_id} target")
            _require_known(event.cause_event_ids, set(events), f"event {event.event_id} cause")
            for cause_id in event.cause_event_ids:
                if events[cause_id].sequence_no >= event.sequence_no:
                    raise ValueError(f"event {event.event_id} cause {cause_id} must occur earlier")
            for change in event.state_changes:
                if change.subject_id not in known_subjects:
                    raise ValueError(f"event {event.event_id} state subject is unknown: {change.subject_id}")

        panel_ids = [item.panel_id for item in self.panels]
        _require_unique(panel_ids, "panel_ids")
        _require_unique([item.sequence_no for item in self.panels], "panel sequence_no values")
        for panel in self.panels:
            _require_known(panel.event_ids, set(events), f"panel {panel.panel_id} event")
            panel_characters = {item.character_id for item in panel.characters}
            _require_known(panel_characters, character_set, f"panel {panel.panel_id} character")
            for item in panel.dialogue:
                if item.speaker_id not in character_set:
                    raise ValueError(f"panel {panel.panel_id} dialogue speaker is unknown: {item.speaker_id}")
                if item.speaker_id not in panel_characters:
                    raise ValueError(f"panel {panel.panel_id} dialogue speaker is not present: {item.speaker_id}")
        return self


class MappingFieldV1(StrictModel):
    upstream_path: str
    scene_job_path: str | None = None
    disposition: Literal["lossless", "textual_fallback", "lost"]
    reason: str


class SceneJobV1MappingAudit(StrictModel):
    schema_name: Literal["SceneJobV1MappingAudit"] = "SceneJobV1MappingAudit"
    source_schema: Literal["UpstreamSceneEnvelopeV1"] = "UpstreamSceneEnvelopeV1"
    target_schema: Literal["SceneJobV1"] = "SceneJobV1"
    fields: list[MappingFieldV1]


MAPPING_AUDIT = SceneJobV1MappingAudit(
    fields=[
        MappingFieldV1(upstream_path="request/project/chapter/scene IDs", scene_job_path="same fields", disposition="lossless", reason="Stable identifiers are copied verbatim."),
        MappingFieldV1(upstream_path="scene summary/location/time/atmosphere", scene_job_path="scene_context", disposition="lossless", reason="SceneJobV1 has equivalent fields."),
        MappingFieldV1(upstream_path="panel action/emotion/dialogue/constraints", scene_job_path="panels", disposition="lossless", reason="Values and ordering are copied verbatim."),
        MappingFieldV1(upstream_path="character appearance", scene_job_path="scene_context.continuity_notes", disposition="textual_fallback", reason="Appearance remains readable but is no longer typed per character."),
        MappingFieldV1(upstream_path="character clothing state", scene_job_path="scene_context.continuity_notes", disposition="textual_fallback", reason="Clothing is flattened to prose; garment IDs and state transitions are unavailable."),
        MappingFieldV1(upstream_path="scene entities", scene_job_path="scene_context.continuity_notes", disposition="textual_fallback", reason="Entity descriptions are flattened to prose."),
        MappingFieldV1(upstream_path="event IDs and causal links", disposition="lost", reason="SceneJobV1 has no event graph."),
        MappingFieldV1(upstream_path="event state before/after and held-object changes", disposition="lost", reason="SceneJobV1 has no structured state store."),
        MappingFieldV1(upstream_path="character entrances/exits", disposition="lost", reason="Panel presence survives but transitions are not represented."),
        MappingFieldV1(upstream_path="dialogue kind", disposition="lost", reason="SceneJobV1 stores only speaker and text."),
        MappingFieldV1(upstream_path="cross-panel movement direction", disposition="lost", reason="SceneJobV1 has no typed motion direction field."),
    ]
)


def map_envelope_to_scene_job(envelope: UpstreamSceneEnvelopeV1) -> SceneJobV1:
    continuity = []
    for character in sorted(envelope.characters, key=lambda item: item.character_id):
        continuity.append(
            f"{character.character_id}（{character.name}）外观：{_fragment(character.appearance)}；"
            f"服装：{'、'.join(_fragment(item) for item in character.clothing)}。"
        )
    for entity in sorted(envelope.scene.entities, key=lambda item: item.entity_id):
        continuity.append(f"场景实体 {entity.entity_id}（{entity.name}）：{_fragment(entity.description)}。")

    panels = []
    for panel in sorted(envelope.panels, key=lambda item: (item.sequence_no, item.panel_id)):
        panels.append(
            PanelIntentV1(
                panel_id=panel.panel_id,
                sequence_no=panel.sequence_no,
                story_intent=panel.story_intent,
                characters=[
                    CharacterIntentV1(
                        character_id=item.character_id,
                        action=item.action,
                        emotion=item.emotion,
                    )
                    for item in panel.characters
                ],
                dialogue=[DialogueV1(speaker_id=item.speaker_id, text=item.text) for item in panel.dialogue],
                constraints=panel.constraints,
                render_profile=panel.render_profile,
            )
        )
    return SceneJobV1(
        request_id=envelope.request_id,
        project_id=envelope.project_id,
        chapter_id=envelope.chapter_id,
        scene_id=envelope.scene_id,
        asset_profile_id=envelope.asset_profile_id,
        scene_context=SceneContextV1(
            summary=envelope.scene.summary,
            location=envelope.scene.location,
            time_of_day=envelope.scene.time_of_day,
            atmosphere=envelope.scene.atmosphere,
            continuity_notes=continuity,
        ),
        panels=panels,
    )


def canonical_envelope_bytes(envelope: UpstreamSceneEnvelopeV1) -> bytes:
    payload = envelope.model_dump(mode="json")
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def envelope_sha256(envelope: UpstreamSceneEnvelopeV1) -> str:
    return hashlib.sha256(canonical_envelope_bytes(envelope)).hexdigest()


def schema_snapshot_sha256() -> str:
    encoded = json.dumps(
        UpstreamSceneEnvelopeV1.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def _require_known(values: Any, known: set[str], label: str) -> None:
    for value in values:
        if value not in known:
            raise ValueError(f"{label} reference is unknown: {value}")


def _fragment(value: str) -> str:
    return value.rstrip("。；;，, ")
