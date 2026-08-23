"""Server-built approved-artifact context for future StoryBible production execution."""

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from comic_agent.database.models import (
    NarrativeAnalysisRunModel,
    SourceChunkModel,
    TimelineGate3RunModel,
)
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelation,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.review import ApprovedProposalBundleV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    StoryBibleCanonicalSnapshotV1,
    StoryBibleProductionContextV1,
    StoryBibleProductionInputV1,
    StoryBibleProductionRunV1,
    StoryBibleTrustedEventOrderV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1, TimelineGate3RunStatus
from comic_agent.services.id_service import checksum_text


@dataclass(frozen=True)
class PreparedStoryBibleProduction:
    """Trusted input, materialized context, and idempotent run reservation."""

    production_input: StoryBibleProductionInputV1
    context: StoryBibleProductionContextV1
    run: StoryBibleProductionRunV1


def canonical_storybible_snapshot_hash(snapshot: StoryBibleCanonicalSnapshotV1) -> str:
    """Hash semantic canonical resources with stable keys and resource ordering."""

    canonical = json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return checksum_text(canonical)


class StoryBibleProductionContextAdapter:
    """Resolve approved Narrative/Timeline artifacts and canonical state from persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._storybible = StoryBibleRepository(session)

    def build(
        self,
        *,
        project_id: str,
        gate2_approved_bundle_id: str,
        approved_timeline_bundle_id: str,
    ) -> StoryBibleProductionContextV1:
        gate2 = self._load_gate2_bundle(project_id, gate2_approved_bundle_id)
        timeline = self._load_timeline_bundle(
            project_id,
            approved_timeline_bundle_id,
            gate2_approved_bundle_id,
        )
        entities: list[EntityProposalV1] = []
        events: list[EventProposalV1] = []
        state_changes: list[StateChangeProposalV1] = []
        evidence: list[EvidenceRefV1] = []
        for item in gate2.approved_proposals:
            proposal = item.source.proposal
            if isinstance(proposal, EntityProposalV1):
                entities.append(proposal)
            elif isinstance(proposal, EventProposalV1):
                events.append(proposal)
            elif isinstance(proposal, StateChangeProposalV1):
                state_changes.append(proposal)
            else:
                continue
            evidence.extend(item.source.aggregated_evidence_refs)
            evidence.extend(proposal.evidence_refs)

        entities.sort(key=lambda item: item.proposal_id)
        events.sort(key=lambda item: item.proposal_id)
        state_changes.sort(key=lambda item: item.proposal_id)
        approved_event_ids = {event.proposal_id for event in events}
        if approved_event_ids != set(timeline.event_ids):
            raise ValueError(
                "Approved Timeline event universe does not match approved Gate 2 events"
            )

        relations = sorted(timeline.temporal_relations, key=lambda item: item.proposal_id)
        evidence.extend(timeline.evidence_refs)
        for relation in relations:
            evidence.extend(relation.evidence_refs)
        trusted_evidence = _deduplicate_evidence(evidence)
        source_chunk_ids = sorted({reference.chunk_id for reference in trusted_evidence})
        source_chunks = self._load_source_chunks(project_id, source_chunk_ids)

        snapshot = self._load_snapshot(project_id)
        snapshot_hash = canonical_storybible_snapshot_hash(snapshot)
        return StoryBibleProductionContextV1(
            project_id=project_id,
            gate2_approved_bundle_id=gate2.bundle_id,
            narrative_analysis_run_id=gate2.analysis_run_id,
            approved_timeline_bundle_id=timeline.bundle_id,
            timeline_run_id=timeline.timeline_run_id,
            approved_entities=entities,
            approved_events=events,
            approved_state_changes=state_changes,
            approved_temporal_relations=relations,
            trusted_event_ids=sorted(approved_event_ids),
            trusted_event_order=derive_storybible_trusted_event_order(
                sorted(approved_event_ids), relations
            ),
            trusted_evidence_refs=trusted_evidence,
            source_chunk_ids=source_chunk_ids,
            source_chunks=source_chunks,
            canonical_snapshot=snapshot,
            canonical_storybible_snapshot_hash=snapshot_hash,
        )

    def _load_gate2_bundle(
        self, project_id: str, bundle_id: str
    ) -> ApprovedProposalBundleV1:
        rows = self._session.scalars(select(NarrativeAnalysisRunModel)).all()
        for row in rows:
            route = row.payload.get("review_gate2_route")
            payload = route.get("approved_proposal_bundle") if isinstance(route, dict) else None
            if payload is None:
                continue
            bundle = ApprovedProposalBundleV1.model_validate(payload)
            if bundle.bundle_id != bundle_id:
                continue
            if row.project_id != project_id or bundle.project_id != project_id:
                raise ValueError("Gate 2 approved bundle belongs to another project")
            if row.analysis_run_id != bundle.analysis_run_id:
                raise ValueError("Gate 2 approved bundle has invalid analysis lineage")
            return bundle
        raise ValueError("Gate 2 approved bundle not found")

    def _load_timeline_bundle(
        self,
        project_id: str,
        bundle_id: str,
        gate2_bundle_id: str,
    ) -> ApprovedTimelineBundleV1:
        rows = self._session.scalars(select(TimelineGate3RunModel)).all()
        for row in rows:
            payload = row.payload.get("approved_timeline_bundle")
            if payload is None:
                continue
            bundle = ApprovedTimelineBundleV1.model_validate(payload)
            if bundle.bundle_id != bundle_id:
                continue
            if row.status != str(TimelineGate3RunStatus.APPROVED):
                raise ValueError("Timeline bundle is not approved")
            if row.project_id != project_id or bundle.project_id != project_id:
                raise ValueError("Approved Timeline bundle belongs to another project")
            if row.timeline_run_id != bundle.timeline_run_id:
                raise ValueError("Approved Timeline bundle has invalid run lineage")
            if (
                row.source_bundle_id != gate2_bundle_id
                or bundle.source_approved_proposal_bundle_id != gate2_bundle_id
            ):
                raise ValueError("Approved Timeline bundle has unrelated Gate 2 lineage")
            return bundle
        raise ValueError("Approved Timeline bundle not found")

    def _load_snapshot(self, project_id: str) -> StoryBibleCanonicalSnapshotV1:
        return StoryBibleCanonicalSnapshotV1(
            project_id=project_id,
            profiles=self._storybible.list_profiles(project_id),
            states=self._storybible.list_states(project_id),
            relationships=self._storybible.list_relationships(project_id),
            world_rules=self._storybible.list_world_rules(project_id),
        )

    def _load_source_chunks(self, project_id: str, chunk_ids: list[str]) -> list[SourceChunkV1]:
        if not chunk_ids:
            return []
        rows = self._session.scalars(
            select(SourceChunkModel).where(SourceChunkModel.chunk_id.in_(chunk_ids))
        ).all()
        owners = {row.chunk_id: row.project_id for row in rows}
        for chunk_id in chunk_ids:
            if chunk_id not in owners:
                raise ValueError(f"approved evidence chunk not found: {chunk_id}")
            if owners[chunk_id] != project_id:
                raise ValueError("approved evidence chunk belongs to another project")
        return [
            SourceChunkV1.model_validate(
                next(row.payload for row in rows if row.chunk_id == chunk_id)
            )
            for chunk_id in chunk_ids
        ]


class StoryBibleProductionInputBuilder:
    """Build trusted context/input and reserve a run without caller-owned derived data."""

    def __init__(self, session: Session) -> None:
        self._adapter = StoryBibleProductionContextAdapter(session)
        self._runs = StoryBibleProductionRunRepository(session)

    def build_and_reserve(
        self,
        *,
        project_id: str,
        gate2_approved_bundle_id: str,
        approved_timeline_bundle_id: str,
        model_identity: str,
    ) -> PreparedStoryBibleProduction:
        context = self._adapter.build(
            project_id=project_id,
            gate2_approved_bundle_id=gate2_approved_bundle_id,
            approved_timeline_bundle_id=approved_timeline_bundle_id,
        )
        production_input = StoryBibleProductionInputV1(
            project_id=project_id,
            gate2_approved_bundle_id=context.gate2_approved_bundle_id,
            approved_timeline_bundle_id=context.approved_timeline_bundle_id,
            canonical_storybible_snapshot_hash=(
                context.canonical_storybible_snapshot_hash
            ),
        )
        run = self._runs.reserve_run(production_input, model_identity=model_identity)
        return PreparedStoryBibleProduction(
            production_input=production_input,
            context=context,
            run=run,
        )


def _deduplicate_evidence(values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
    keyed = {
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ): value
        for value in values
    }
    return [keyed[key] for key in sorted(keyed)]


def derive_storybible_trusted_event_order(
    event_ids: list[str],
    relations: list[TemporalRelationProposalV1],
) -> list[StoryBibleTrustedEventOrderV1]:
    predecessors = {event_id: set[str]() for event_id in event_ids}
    for relation in relations:
        if relation.relation == TemporalRelation.BEFORE:
            predecessors[relation.target_event_id].add(relation.source_event_id)
        elif relation.relation == TemporalRelation.AFTER:
            predecessors[relation.source_event_id].add(relation.target_event_id)

    changed = True
    while changed:
        changed = False
        for event_id in event_ids:
            expanded = set(predecessors[event_id])
            for predecessor in tuple(predecessors[event_id]):
                expanded.update(predecessors[predecessor])
            if expanded != predecessors[event_id]:
                predecessors[event_id] = expanded
                changed = True
    if any(event_id in predecessors[event_id] for event_id in event_ids):
        raise ValueError("Approved Timeline strict relations contain a cycle")

    is_total_order = all(
        left in predecessors[right] or right in predecessors[left]
        for index, left in enumerate(event_ids)
        for right in event_ids[index + 1 :]
    )
    return [
        StoryBibleTrustedEventOrderV1(
            event_id=event_id,
            strict_predecessor_event_ids=sorted(predecessors[event_id]),
            resolved_order=len(predecessors[event_id]) if is_total_order else None,
        )
        for event_id in event_ids
    ]
