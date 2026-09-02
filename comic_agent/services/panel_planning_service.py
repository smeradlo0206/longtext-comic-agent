"""Deterministic scene-to-panel planning for an external image generation agent."""

from comic_agent.schemas.comic_planning import PanelPlanV1, ScenePlanV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryEntityKind,
    StoryEntityProfileV1,
)
from comic_agent.services.id_service import stable_id


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
            shot_type="MEDIUM",
            camera_angle="EYE_LEVEL",
            composition="CENTERED",
            character_ids=list(scene.character_ids),
            character_state_ids=[state.state_id for state in applicable_states],
            character_actions=character_actions,
            expressions={},
            background=background,
            location_entity_id=location_entity_id,
            objects=[],
            atmosphere=scene.emotion,
            dialogue=[],
            narration=None,
            caption=scene.summary,
            previous_panel_reference=previous_panel_reference,
            continuity_notes=list(scene.continuity_notes),
            related_event_ids=list(scene.related_event_ids),
            evidence_refs=list(scene.evidence_refs),
        )

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
