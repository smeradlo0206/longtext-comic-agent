"""Timeline input must retain only Gate 2's proven Proposal links."""

from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    EntityProposalV1,
    EventProposalV1,
    EvidenceRefV1,
    NarrativeAnalysisReviewRouteV1,
    ReferenceResolutionDecisionV1,
    ReviewableProposalEnvelopeV1,
)
from comic_agent.schemas.review import ReviewGate2RoutingDecision, ReviewGate2RunStatus
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_timeline_input_adapter import NarrativeTimelineInputAdapter


def test_timeline_input_materializes_only_gate2_resolved_participant_mention() -> None:
    text = "Lin closes the gate."
    evidence = [EvidenceRefV1(chunk_id="chunk-1", quote_text=text)]
    entity = EntityProposalV1(
        proposal_id="entity-lin",
        entity_type="CHARACTER",
        canonical_name="Lin",
        evidence_refs=evidence,
        confidence=0.9,
    )
    event = EventProposalV1(
        schema_version="1.1",
        proposal_id="event-1",
        event_type="ACTION",
        summary=text,
        participant_mentions=[
            {
                "mention_text": "Lin",
                "resolution_status": "UNRESOLVED",
                "proposal_id": None,
                "proposal_schema": None,
            }
        ],
        actor_resolution_status="KNOWN",
        evidence_refs=evidence,
        confidence=0.9,
        reality_layer="PRIMARY",
    )
    reference = ReferenceResolutionDecisionV1(
        reference_path="participant_mentions[0]",
        mention_text="Lin",
        expected_target_schemas=["EntityProposalV1"],
        required_for_downstream=False,
        status="RESOLVED",
        candidates=[
            {
                "target_proposal_id": entity.proposal_id,
                "target_proposal_schema": "EntityProposalV1",
                "match_basis": "EXACT_UNIQUE_MENTION",
            }
        ],
        selected_target_proposal_id=entity.proposal_id,
        selected_target_proposal_schema="EntityProposalV1",
        resolution_basis="EXACT_UNIQUE_MENTION",
    )
    event_item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="event_extraction",
            proposal_schema="EventProposalV1",
            proposal=event,
            agent_run_ids=["event-run"],
            aggregated_evidence_refs=evidence,
        ),
        review_decision_id="event-decision",
        reference_decisions=[reference],
    )
    entity_item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="entity_extraction",
            proposal_schema="EntityProposalV1",
            proposal=entity,
            agent_run_ids=["entity-run"],
            aggregated_evidence_refs=evidence,
        ),
        review_decision_id="entity-decision",
    )
    bundle = ApprovedProposalBundleV1(
        bundle_id="bundle-1",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        policy_id="policy-1",
        approved_proposals=[entity_item, event_item],
        review_decision_ids=["entity-decision", "event-decision"],
    )
    route = NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        decision=ReviewGate2RoutingDecision.APPROVED,
        review_status=ReviewGate2RunStatus.COMPLETED,
        total_count=2,
        approved_count=2,
        rejected_count=0,
        held_count=0,
        approved_proposal_bundle=bundle,
    )
    chunk = SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )

    timeline_input = NarrativeTimelineInputAdapter().build_from_approved_bundle(
        route=route, source_chunks=[chunk]
    )

    assert timeline_input.event_proposals[0].participant_ids == ["entity-lin"]
    assert event.participant_ids == []


def test_timeline_input_replaces_resolved_location_mention_with_entity_id() -> None:
    text = "Lin reaches the east gate."
    evidence = [EvidenceRefV1(chunk_id="chunk-1", quote_text=text)]
    location = EntityProposalV1(
        proposal_id="entity-east-gate",
        entity_type="LOCATION",
        canonical_name="east gate",
        evidence_refs=evidence,
        confidence=0.9,
    )
    event = EventProposalV1(
        schema_version="1.1",
        proposal_id="event-1",
        event_type="ACTION",
        summary=text,
        participant_ids=["entity-lin"],
        actor_resolution_status="KNOWN",
        location_mention={
            "mention_text": "east gate",
            "resolution_status": "UNRESOLVED",
            "proposal_id": None,
            "proposal_schema": None,
        },
        evidence_refs=evidence,
        confidence=0.9,
        reality_layer="PRIMARY",
    )
    reference = ReferenceResolutionDecisionV1(
        reference_path="location_mention",
        mention_text="east gate",
        expected_target_schemas=["EntityProposalV1"],
        required_for_downstream=False,
        status="RESOLVED",
        candidates=[
            {
                "target_proposal_id": location.proposal_id,
                "target_proposal_schema": "EntityProposalV1",
                "match_basis": "EXACT_UNIQUE_MENTION",
            }
        ],
        selected_target_proposal_id=location.proposal_id,
        selected_target_proposal_schema="EntityProposalV1",
        resolution_basis="EXACT_UNIQUE_MENTION",
    )
    event_item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="event_extraction",
            proposal_schema="EventProposalV1",
            proposal=event,
            agent_run_ids=["event-run"],
            aggregated_evidence_refs=evidence,
        ),
        review_decision_id="event-decision",
        reference_decisions=[reference],
    )
    location_item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="entity_extraction",
            proposal_schema="EntityProposalV1",
            proposal=location,
            agent_run_ids=["entity-run"],
            aggregated_evidence_refs=evidence,
        ),
        review_decision_id="entity-decision",
    )
    bundle = ApprovedProposalBundleV1(
        bundle_id="bundle-1",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        policy_id="policy-1",
        approved_proposals=[location_item, event_item],
        review_decision_ids=["entity-decision", "event-decision"],
    )
    route = NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        decision=ReviewGate2RoutingDecision.APPROVED,
        review_status=ReviewGate2RunStatus.COMPLETED,
        total_count=2,
        approved_count=2,
        rejected_count=0,
        held_count=0,
        approved_proposal_bundle=bundle,
    )
    chunk = SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )

    timeline_input = NarrativeTimelineInputAdapter().build_from_approved_bundle(
        route=route, source_chunks=[chunk]
    )

    materialized = timeline_input.event_proposals[0]
    assert materialized.location_id == "entity-east-gate"
    assert materialized.location_mention is None
    assert event.location_id is None
    assert event.location_mention is not None
