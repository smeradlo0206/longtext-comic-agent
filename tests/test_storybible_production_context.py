"""Trusted approved-artifact context and canonical snapshot coverage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.database.models import (
    NarrativeAnalysisRunModel,
    SourceChunkModel,
    TimelineGate3RunModel,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.review import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    ReviewableProposalEnvelopeV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import StoryEntityProfileV1
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1, TimelineGate3RunStatus
from comic_agent.services.id_service import checksum_text
from comic_agent.services.storybible_production_context import (
    StoryBibleProductionContextAdapter,
    StoryBibleProductionInputBuilder,
    derive_storybible_trusted_event_order,
)


def _evidence(chunk_id: str = "chunk-1") -> EvidenceRefV1:
    return EvidenceRefV1(chunk_id=chunk_id, quote_text="trusted source")


def _event(proposal_id: str) -> EventProposalV1:
    return EventProposalV1(
        proposal_id=proposal_id,
        event_type="EVENT",
        summary=f"Approved {proposal_id}",
        evidence_refs=[_evidence()],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def _approved_item(
    proposal: EntityProposalV1 | EventProposalV1 | StateChangeProposalV1,
) -> ApprovedProposalItemV1:
    if isinstance(proposal, EntityProposalV1):
        mode = "entity_extraction"
        schema = "EntityProposalV1"
    elif isinstance(proposal, EventProposalV1):
        mode = "event_extraction"
        schema = "EventProposalV1"
    else:
        mode = "state_change_extraction"
        schema = "StateChangeProposalV1"
    return ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode=mode,
            proposal_schema=schema,
            proposal=proposal,
            agent_run_ids=[f"agent-{proposal.proposal_id}"],
            aggregated_evidence_refs=proposal.evidence_refs,
        ),
        review_decision_id=f"decision-{proposal.proposal_id}",
    )


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'production-context.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def _persist_source(session: Session, *, project_id: str = "project-1") -> None:
    text = "trusted source"
    chunk = SourceChunkV1(
        chunk_id="chunk-1",
        project_id=project_id,
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )
    session.add(
        SourceChunkModel(
            chunk_id=chunk.chunk_id,
            project_id=chunk.project_id,
            document_id=chunk.document_id,
            chapter_id=chunk.chapter_id,
            order=chunk.order,
            text=chunk.text,
            source_page=None,
            char_start=None,
            char_end=None,
            checksum=chunk.checksum,
            payload=chunk.model_dump(mode="json"),
        )
    )
    session.commit()


def _persist_artifacts(session: Session) -> None:
    entity = EntityProposalV1(
        proposal_id="entity-1",
        entity_type="CHARACTER",
        canonical_name="Lin",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )
    events = [_event("event-1"), _event("event-2")]
    state_change = StateChangeProposalV1(
        schema_version="1.0",
        proposal_id="state-change-1",
        event_id="event-1",
        target_entity_id="entity-1",
        attribute_path="health.injury",
        old_value=None,
        new_value="injured",
        persistent=False,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=[_evidence()],
        confidence=0.9,
    )
    items = [
        _approved_item(entity),
        *(_approved_item(event) for event in events),
        _approved_item(state_change),
    ]
    gate2 = ApprovedProposalBundleV1(
        bundle_id="gate2-bundle-1",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        policy_id="policy-1",
        approved_proposals=items,
        review_decision_ids=[item.review_decision_id for item in items],
    )
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1",
        source_event_id="event-1",
        target_event_id="event-2",
        relation="BEFORE",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )
    timeline = ApprovedTimelineBundleV1(
        bundle_id="timeline-bundle-1",
        project_id="project-1",
        source_approved_proposal_bundle_id=gate2.bundle_id,
        source_gate2_review_id=gate2.review_run_id,
        source_gate2_route_id=gate2.analysis_run_id,
        timeline_run_id="timeline-run-1",
        gate3_review_id="gate3-review-1",
        gate3_route_id="gate3-route-1",
        temporal_relations=[relation],
        event_ids=[event.proposal_id for event in events],
        evidence_refs=[_evidence()],
    )
    now = datetime.now(UTC)
    session.add(
        NarrativeAnalysisRunModel(
            analysis_run_id=gate2.analysis_run_id,
            project_id=gate2.project_id,
            document_id=gate2.document_id,
            status="SUCCEEDED",
            payload={
                "review_gate2_route": {
                    "approved_proposal_bundle": gate2.model_dump(mode="json")
                }
            },
            result_payload=None,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        TimelineGate3RunModel(
            timeline_run_id=timeline.timeline_run_id,
            project_id=timeline.project_id,
            source_bundle_id=gate2.bundle_id,
            idempotency_key="timeline-key-1",
            status=str(TimelineGate3RunStatus.APPROVED),
            payload={"approved_timeline_bundle": timeline.model_dump(mode="json")},
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


def test_adapter_builds_only_trusted_approved_material(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _persist_source(session)
    _persist_artifacts(session)

    context = StoryBibleProductionContextAdapter(session).build(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-bundle-1",
        approved_timeline_bundle_id="timeline-bundle-1",
    )

    assert [item.proposal_id for item in context.approved_entities] == ["entity-1"]
    assert [item.proposal_id for item in context.approved_events] == ["event-1", "event-2"]
    assert [item.proposal_id for item in context.approved_state_changes] == [
        "state-change-1"
    ]
    assert context.trusted_event_ids == ["event-1", "event-2"]
    assert [item.resolved_order for item in context.trusted_event_order] == [0, 1]
    assert context.source_chunk_ids == ["chunk-1"]


def test_unknown_or_partial_relations_do_not_manufacture_integer_order() -> None:
    relations = [
        TemporalRelationProposalV1(
            proposal_id="known",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="BEFORE",
            evidence_refs=[_evidence()],
            confidence=0.9,
        ),
        TemporalRelationProposalV1(
            proposal_id="unknown",
            source_event_id="event-2",
            target_event_id="event-3",
            relation="UNKNOWN",
            confidence=0,
        ),
    ]

    order = derive_storybible_trusted_event_order(
        ["event-1", "event-2", "event-3"], relations
    )

    assert [item.resolved_order for item in order] == [None, None, None]
    assert order[1].strict_predecessor_event_ids == ["event-1"]
    assert order[2].strict_predecessor_event_ids == []


def test_builder_owns_snapshot_hash_and_snapshot_change_creates_new_run(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    _persist_source(session)
    _persist_artifacts(session)
    builder = StoryBibleProductionInputBuilder(session)
    first = builder.build_and_reserve(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-bundle-1",
        approved_timeline_bundle_id="timeline-bundle-1",
        model_identity="curator-model-v1",
    )
    duplicate = builder.build_and_reserve(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-bundle-1",
        approved_timeline_bundle_id="timeline-bundle-1",
        model_identity="curator-model-v1",
    )
    StoryBibleRepository(session).apply_canonical_update(
        StoryEntityProfileV1(
            profile_id="profile-1",
            project_id="project-1",
            entity_kind="PERSON",
            canonical_name="Lin",
            evidence_refs=[_evidence()],
        ),
        plan_id="plan-1",
    )
    changed = builder.build_and_reserve(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-bundle-1",
        approved_timeline_bundle_id="timeline-bundle-1",
        model_identity="curator-model-v1",
    )

    assert duplicate.run.run_id == first.run.run_id
    assert changed.production_input.canonical_storybible_snapshot_hash != (
        first.production_input.canonical_storybible_snapshot_hash
    )
    assert changed.run.run_id != first.run.run_id
    assert changed.context.canonical_snapshot.profiles[0].profile_id == "profile-1"


def test_adapter_rejects_evidence_chunk_from_another_project(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _persist_source(session, project_id="project-2")
    _persist_artifacts(session)

    with pytest.raises(ValueError, match="chunk belongs to another project"):
        StoryBibleProductionContextAdapter(session).build(
            project_id="project-1",
            gate2_approved_bundle_id="gate2-bundle-1",
            approved_timeline_bundle_id="timeline-bundle-1",
        )
