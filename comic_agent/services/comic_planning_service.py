"""Deterministic conversion of frozen story facts into scene plans."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_planning import ComicPlanningInputV1, ScenePlanV1
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.storybible import ApprovedStoryBibleBundleV1, StoryEntityKind
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.id_service import stable_id


class ComicPlanningService:
    """Create scenes without adding facts or invoking a model/provider."""

    def plan(
        self,
        *,
        storybible: ApprovedStoryBibleBundleV1,
        timeline: ApprovedTimelineBundleV1,
        events: list[EventProposalV1] | None = None,
    ) -> list[ScenePlanV1]:
        planning_input = self._validate_input(storybible=storybible, timeline=timeline)
        event_map = {event.proposal_id: event for event in (events or [])}
        if events is not None and set(event_map) != set(timeline.event_ids):
            raise ValueError("Comic Planning events must exactly match the Timeline universe")
        people = {
            entity.profile_id: entity
            for entity in storybible.entities
            if entity.entity_kind == StoryEntityKind.PERSON
        }
        states_by_event: dict[str, set[str]] = {}
        for state in storybible.state_changes:
            for event_id in (
                state.triggering_event_id,
                state.valid_from_event_id,
                state.valid_until_event_id,
            ):
                if event_id is not None and state.profile_id in people:
                    states_by_event.setdefault(event_id, set()).add(state.profile_id)

        scenes: list[ScenePlanV1] = []
        for index, event_id in enumerate(timeline.event_ids):
            event = event_map.get(event_id)
            character_ids = sorted(states_by_event.get(event_id, set()))
            evidence_refs = self._evidence_for_event(event_id, timeline, event)
            summary = event.summary if event is not None else f"Present event {index + 1}."
            scenes.append(
                ScenePlanV1(
                    scene_id=stable_id(
                        "comic-scene",
                        planning_input.project_id,
                        planning_input.storybible_bundle_id,
                        planning_input.timeline_bundle_id,
                        event_id,
                    ),
                    project_id=planning_input.project_id,
                    storybible_bundle_id=planning_input.storybible_bundle_id,
                    timeline_bundle_id=planning_input.timeline_bundle_id,
                    title=f"Scene {index + 1}",
                    summary=summary,
                    purpose=f"Visualize approved event {index + 1} from its source evidence.",
                    related_event_ids=[event_id],
                    character_ids=character_ids,
                    location=None,
                    time=f"Approved source order {index + 1}",
                    emotion=None,
                    continuity_notes=[
                        "Do not introduce facts outside the approved StoryBible and Timeline."
                    ],
                    evidence_refs=evidence_refs,
                )
            )
        return scenes

    @staticmethod
    def _validate_input(
        *,
        storybible: ApprovedStoryBibleBundleV1,
        timeline: ApprovedTimelineBundleV1,
    ) -> ComicPlanningInputV1:
        if storybible.project_id != timeline.project_id:
            raise ValueError("Comic Planning bundles must belong to the same project")
        if (
            storybible.review_metadata.source_approved_timeline_bundle_id
            != timeline.bundle_id
        ):
            raise ValueError("StoryBible freeze lineage must reference the Timeline bundle")
        if not timeline.event_ids:
            raise ValueError("Comic Planning requires at least one approved Timeline event")
        return ComicPlanningInputV1(
            project_id=storybible.project_id,
            storybible_bundle_id=storybible.bundle_id,
            timeline_bundle_id=timeline.bundle_id,
        )

    @staticmethod
    def _evidence_for_event(
        event_id: str,
        timeline: ApprovedTimelineBundleV1,
        event: EventProposalV1 | None = None,
    ) -> list[EvidenceRefV1]:
        if event is not None:
            trusted = {
                evidence.model_dump_json()
                for evidence in timeline.evidence_refs
            }
            if any(evidence.model_dump_json() not in trusted for evidence in event.evidence_refs):
                raise ValueError("Comic Planning event evidence escaped the approved Timeline")
            return list(event.evidence_refs)
        related = [
            evidence
            for relation in timeline.temporal_relations
            if event_id in {relation.source_event_id, relation.target_event_id}
            for evidence in relation.evidence_refs
        ]
        candidates = related or timeline.evidence_refs
        unique: list[EvidenceRefV1] = []
        for evidence in candidates:
            if evidence not in unique:
                unique.append(evidence)
        return unique
