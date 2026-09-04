"""Deterministic scene-to-panel planning for an external image generation agent."""

import re

from comic_agent.schemas.comic_planning import PanelPlanV1, ScenePlanV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryEntityKind,
    StoryEntityProfileV1,
)
from comic_agent.services.id_service import stable_id

_SPOKEN_DIALOGUE_RE = re.compile(
    r"(?:说|问|答|道|喊|提醒|告诉|招呼|回应)[^“「『\"]{0,40}"
    r"[“「『\"]([^”」』\"]{1,120})[”」』\"]"
)
_SHOT_TYPES = (
    "MEDIUM",
    "WIDE",
    "MEDIUM_CLOSE_UP",
    "OVER_THE_SHOULDER",
    "CLOSE_UP",
    "WIDE",
)
_CAMERA_ANGLES = (
    "EYE_LEVEL",
    "EYE_LEVEL",
    "THREE_QUARTER",
    "EYE_LEVEL",
    "SLIGHT_LOW",
    "EYE_LEVEL",
)
_COMPOSITIONS = (
    "CENTERED",
    "RULE_OF_THIRDS",
    "LAYERED_DEPTH",
    "DIAGONAL",
    "CLOSE_FOCUS",
    "OPEN_BALANCE",
)


class PanelPlanningService:
    """Create a render-ready structural panel without generating image prompts."""

    def plan(
        self,
        *,
        scene: ScenePlanV1,
        storybible: ApprovedStoryBibleBundleV1,
        index: int = 0,
        aspect_ratio: str = "1:1",
        previous_panel_reference: str | None = None,
        source_chunks: list[SourceChunkV1] | None = None,
    ) -> PanelPlanV1:
        if scene.project_id != storybible.project_id:
            raise ValueError("Scene and StoryBible must belong to the same project")
        if scene.storybible_bundle_id != storybible.bundle_id:
            raise ValueError("Scene must reference the supplied StoryBible bundle")
        people = {
            entity.profile_id
            for entity in storybible.entities
            if entity.entity_kind == StoryEntityKind.PERSON
        }
        if not set(scene.character_ids).issubset(people):
            raise ValueError("Scene characters must come from the approved StoryBible")

        event_ids = set(scene.related_event_ids)
        applicable_states = sorted(
            (
                state
                for state in storybible.state_changes
                if state.profile_id in people
                and state.profile_id in scene.character_ids
                and event_ids.intersection(
                    {
                        state.triggering_event_id,
                        state.valid_from_event_id,
                        state.valid_until_event_id,
                    }
                )
            ),
            key=lambda state: state.state_id,
        )
        character_actions: dict[str, str] = {}
        for state in applicable_states:
            activity = state.state.get("activity")
            if (
                state.profile_id not in character_actions
                and isinstance(activity, str)
                and activity.strip()
            ):
                character_actions[state.profile_id] = activity

        locations = {
            entity.profile_id: entity
            for entity in storybible.entities
            if entity.entity_kind == StoryEntityKind.LOCATION
        }
        event_location_ids = {
            state.profile_id
            for state in storybible.state_changes
            if state.profile_id in locations
            and event_ids.intersection(
                {
                    state.triggering_event_id,
                    state.valid_from_event_id,
                    state.valid_until_event_id,
                }
            )
        }
        location_entity_id = self._resolve_location(
            scene.location, locations, event_location_ids
        )
        background = (
            locations[location_entity_id].canonical_name
            if location_entity_id is not None
            else None
        )
        dialogue = self._source_dialogue(scene, source_chunks)

        return PanelPlanV1(
            panel_id=stable_id("comic-panel", scene.scene_id, str(index), aspect_ratio),
            project_id=scene.project_id,
            scene_id=scene.scene_id,
            index=index,
            storybible_bundle_id=scene.storybible_bundle_id,
            timeline_bundle_id=scene.timeline_bundle_id,
            panel_purpose=scene.purpose,
            narrative_beat=scene.summary,
            aspect_ratio=aspect_ratio,
            shot_type=_SHOT_TYPES[index % len(_SHOT_TYPES)],
            camera_angle=_CAMERA_ANGLES[index % len(_CAMERA_ANGLES)],
            composition=_COMPOSITIONS[index % len(_COMPOSITIONS)],
            character_ids=list(scene.character_ids),
            character_state_ids=[state.state_id for state in applicable_states],
            character_actions=character_actions,
            expressions={},
            background=background,
            location_entity_id=location_entity_id,
            objects=[],
            atmosphere=scene.emotion,
            dialogue=dialogue,
            narration=None,
            caption=None if dialogue else scene.summary,
            previous_panel_reference=previous_panel_reference,
            continuity_notes=list(scene.continuity_notes),
            related_event_ids=list(scene.related_event_ids),
            evidence_refs=list(scene.evidence_refs),
        )

    @classmethod
    def _source_dialogue(
        cls,
        scene: ScenePlanV1,
        source_chunks: list[SourceChunkV1] | None,
    ) -> list[str]:
        """Extract only explicit spoken Chinese quotes from trusted evidence text."""

        if source_chunks is None:
            return []
        chunks_by_id = {chunk.chunk_id: chunk for chunk in source_chunks}
        dialogue: list[str] = []
        for evidence in scene.evidence_refs:
            chunk = chunks_by_id.get(evidence.chunk_id)
            if chunk is None or chunk.project_id != scene.project_id:
                raise ValueError("Panel Planning evidence is outside supplied source chunks")
            text = chunk.text
            if evidence.quote_start is not None and evidence.quote_end is not None:
                if evidence.quote_end > len(text):
                    raise ValueError("Panel Planning evidence range exceeds its source chunk")
                text = text[evidence.quote_start : evidence.quote_end]
                if evidence.quote_text is not None and evidence.quote_text != text:
                    raise ValueError("Panel Planning evidence span does not match source text")
            elif evidence.quote_text is not None:
                if evidence.quote_text not in text:
                    raise ValueError("Panel Planning evidence quote does not match source text")
                text = evidence.quote_text
            for match in _SPOKEN_DIALOGUE_RE.finditer(text):
                quoted = match.group(1).strip()
                if quoted and quoted not in dialogue:
                    dialogue.append(quoted)
        return dialogue[:4]

    @staticmethod
    def _resolve_location(
        scene_location: str | None,
        locations: dict[str, StoryEntityProfileV1],
        event_location_ids: set[str],
    ) -> str | None:
        if scene_location is not None:
            if scene_location in locations:
                return scene_location
            matching_ids = [
                location_id
                for location_id, location in locations.items()
                if location.canonical_name == scene_location
            ]
            if len(matching_ids) == 1:
                return matching_ids[0]
            raise ValueError("Scene location must reference a canonical StoryBible location")
        if len(event_location_ids) == 1:
            return next(iter(event_location_ids))
        return None
