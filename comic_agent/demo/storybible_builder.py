"""Deterministic StoryBible fallback used only by the explicit demo runner."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EntityProposalV1, EventProposalV1, StateChangeProposalV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryBibleReviewMetadataV1,
    StoryEntityKind,
    StoryEntityProfileV1,
    StoryEntityStateV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.id_service import stable_id


class DemoStoryBibleBuilder:
    """Build the smallest comic-planning-compatible bundle from trusted proposals."""

    def build(
        self,
        *,
        project_id: str,
        source_chunks: Iterable[Any],
        narrative_entities: Iterable[EntityProposalV1],
        narrative_events: Iterable[EventProposalV1],
        state_changes: Iterable[StateChangeProposalV1] = (),
        timeline: ApprovedTimelineBundleV1,
    ) -> ApprovedStoryBibleBundleV1:
        chunks = list(source_chunks)
        entities_in = list(narrative_entities)
        events = list(narrative_events)
        changes = list(state_changes)
        proposals: list[EntityProposalV1 | EventProposalV1 | StateChangeProposalV1] = [
            *entities_in,
            *events,
            *changes,
        ]
        evidence = self._unique_evidence(
            [ref for item in proposals for ref in item.evidence_refs] + list(timeline.evidence_refs)
        )
        profiles: list[StoryEntityProfileV1] = []
        proposal_to_profile: dict[str, str] = {}
        for entity in entities_in:
            kind = self._kind(str(entity.entity_type))
            if kind is None:
                continue
            profile_id = stable_id("demo-profile", project_id, entity.proposal_id)
            proposal_to_profile[entity.proposal_id] = profile_id
            profiles.append(
                StoryEntityProfileV1(
                    profile_id=profile_id,
                    project_id=project_id,
                    entity_kind=kind,
                    canonical_name=entity.canonical_name,
                    aliases=sorted(set(entity.aliases)),
                    attributes={"demo_source_proposal_id": entity.proposal_id},
                    evidence_refs=self._unique_evidence(entity.evidence_refs),
                )
            )
        states: list[StoryEntityStateV1] = []
        event_ids = set(timeline.event_ids)
        for change in changes:
            target_id = change.target_entity_id
            event_id = change.event_id
            if change.schema_version != "1.0":
                target_id = getattr(change.target, "entity_proposal_id", None)
                event_id = getattr(change.event, "event_proposal_id", None)
            state_profile_id = proposal_to_profile.get(target_id or "")
            if state_profile_id is None:
                continue
            states.append(
                StoryEntityStateV1(
                    state_id=stable_id("demo-state", project_id, change.proposal_id),
                    project_id=project_id,
                    profile_id=state_profile_id,
                    state={str(change.attribute_path): change.new_value},
                    triggering_event_id=event_id if event_id in event_ids else None,
                    evidence_refs=self._unique_evidence(change.evidence_refs),
                )
            )
        seed = "|".join(
            [project_id, timeline.bundle_id]
            + [getattr(chunk, "checksum", getattr(chunk, "chunk_id", "")) for chunk in chunks]
            + [item.proposal_id for item in entities_in]
            + [item.proposal_id for item in events]
        )
        bundle_id = stable_id("demo-storybible-bundle", seed)
        fixed_time = datetime(2000, 1, 1, tzinfo=UTC)
        return ApprovedStoryBibleBundleV1(
            bundle_id=bundle_id,
            project_id=project_id,
            source_storybible_run_id=stable_id("demo-storybible-run", seed),
            snapshot_hash=stable_id("demo-storybible-snapshot", seed),
            entities=sorted(profiles, key=lambda item: item.profile_id),
            state_changes=sorted(states, key=lambda item: item.state_id),
            evidence_refs=evidence,
            review_metadata=StoryBibleReviewMetadataV1(
                review_id=stable_id("demo-review", seed),
                decision="APPROVE",
                proposal_hash=stable_id("demo-proposal", seed),
                source_approved_timeline_bundle_id=timeline.bundle_id,
                reviewed_at=fixed_time,
                frozen_at=fixed_time,
            ),
        )

    @staticmethod
    def _kind(value: str) -> StoryEntityKind | None:
        value = value.upper()
        if value in {"PERSON", "CHARACTER", "HUMAN", "CREATURE"}:
            return StoryEntityKind.PERSON
        if value in {"LOCATION", "PLACE"}:
            return StoryEntityKind.LOCATION
        if value in {"ORGANIZATION", "ORG"}:
            return StoryEntityKind.ORGANIZATION
        return None

    @staticmethod
    def _unique_evidence(items: Iterable[EvidenceRefV1]) -> list[EvidenceRefV1]:
        result: list[EvidenceRefV1] = []
        for item in items:
            if item not in result:
                result.append(item)
        return result
