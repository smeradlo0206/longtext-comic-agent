"""Failure-injection verification for the Timeline execution handoff."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.reliability import ProviderFailureCategory
from comic_agent.schemas.review import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    NarrativeAnalysisReviewRouteV1,
    ReviewableProposalEnvelopeV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
)
from comic_agent.schemas.timeline_execution import (
    TimelineExecutionBundleV1,
    TimelineExecutionDiagnosticV1,
    TimelineExecutionFailedItemV1,
    TimelineExecutionInputReferenceV1,
    TimelineExecutionProvenanceV1,
    TimelineExecutionStatus,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_timeline_coordinator import NarrativeTimelineCoordinator
from comic_agent.services.review_gate3_service import ReviewGate3Service


def _evidence(text: str = "The bell rings") -> EvidenceRefV1:
    return EvidenceRefV1(chunk_id="chunk-1", quote_text=text)


def _events() -> list[EventProposalV1]:
    evidence = _evidence()
    return [
        EventProposalV1(
            proposal_id=f"event-{index}",
            event_type="school_event",
            summary=f"Event {index}",
            participant_ids=[],
            location_id=None,
            evidence_refs=[evidence],
            confidence=0.9,
            reality_layer=RealityLayer.PRIMARY,
        )
        for index in range(1, 5)
    ]


def _route() -> NarrativeAnalysisReviewRouteV1:
    events = _events()
    items = [
        ApprovedProposalItemV1(
            source=ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=event.evidence_refs,
            ),
            review_decision_id=f"gate2-decision-{event.proposal_id}",
        )
        for event in events
    ]
    bundle = ApprovedProposalBundleV1(
        bundle_id="gate2-bundle-1",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        policy_id="gate2-policy-1",
        approved_proposals=items,
        review_decision_ids=[item.review_decision_id for item in items],
    )
    return NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        decision=ReviewGate2RoutingDecision.APPROVED,
        review_status=ReviewGate2RunStatus.COMPLETED,
        total_count=len(items),
        approved_count=len(items),
        rejected_count=0,
        held_count=0,
        approved_proposal_bundle=bundle,
    )


def _chunk() -> SourceChunkV1:
    text = "The bell rings."
    return SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )


def _input_for_bundle() -> TimelineAnalysisInputV1:
    events = _events()
    return TimelineAnalysisInputV1(
        project_id="project-1",
        source_approved_bundle_id="gate2-bundle-1",
        source_review_run_id="gate2-review-1",
        event_proposals=events,
    )


def _coordinator(tmp_path: Path, runner: object) -> NarrativeTimelineCoordinator:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'failure-injection.db'}")
    Base.metadata.create_all(engine)
    return NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=runner,  # type: ignore[arg-type]
        agent_run_repository=AgentRunRepository(Session(engine)),
    )


class _SuccessfulRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        evidence = input_context.event_proposals[0].evidence_refs
        return TimelineAnalysisProposalV1(
            proposal_id="timeline-proposal-success",
            project_id=input_context.project_id,
            temporal_relations=[
                TemporalRelationProposalV1(
                    proposal_id="relation-1",
                    source_event_id="event-1",
                    target_event_id="event-2",
                    relation="BEFORE",
                    evidence_refs=evidence,
                    confidence=0.9,
                )
            ],
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=evidence,
            confidence=0.9,
        )


class _SchemaFailureRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise ProviderResponseError(
            "provider response is not persisted",
            diagnostics={
                "schema_error_kind": "literal_error",
                "schema_error_field_paths": ["temporal_relations[0].relation"],
                "schema_error_rule_codes": ["TIMELINE_PAIR_SCHEMA_INVALID"],
                "expected_output_schema": "TimelinePairInferenceV1",
                "raw_response": "must not persist",
            },
        )


class _TimeoutRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise TimeoutError("provider timeout must not be persisted")


def _partial_bundle() -> TimelineExecutionBundleV1:
    evidence = _evidence()
    relations = [
        TemporalRelationProposalV1(
            proposal_id=f"relation-{index}",
            source_event_id=f"event-{index}",
            target_event_id=f"event-{index + 1}",
            relation="BEFORE",
            evidence_refs=[evidence],
            confidence=0.9,
        )
        for index in range(1, 4)
    ]
    failed_items = [
        TimelineExecutionFailedItemV1(
            pair_id=f"pair{index}",
            failure_category=ProviderFailureCategory.SCHEMA,
            field_path="relation",
            failure_origin="LLM_OUTPUT_SCHEMA_INVALID",
            safe_issue_codes=["TIMELINE_PAIR_SCHEMA_INVALID"],
        )
        for index in (4, 5)
    ]
    return TimelineExecutionBundleV1(
        bundle_id="timeline-execution-partial",
        project_id="project-1",
        timeline_run_id="timeline-run-partial",
        status=TimelineExecutionStatus.PARTIAL_FAILED,
        input_reference=TimelineExecutionInputReferenceV1(
            source_approved_proposal_bundle_id="gate2-bundle-1",
            source_gate2_review_id="gate2-review-1",
            source_gate2_route_id="analysis-1",
            event_proposal_ids=[event.proposal_id for event in _events()],
        ),
        candidate_relations=relations,
        failed_items=failed_items,
        diagnostics=[
            TimelineExecutionDiagnosticV1(
                failure_origin="LLM_OUTPUT_SCHEMA_INVALID",
                field_path="relation",
                error_type="literal_error",
                message_type="enum_error",
            )
        ],
        evidence_refs=[evidence],
        provenance=TimelineExecutionProvenanceV1(
            timeline_agent_run_id="timeline-agent-partial",
            gate3_reviewer_agent_run_id="gate3-agent-partial",
        ),
    )


def test_case1_success_creates_bundle_and_approved_gate3(tmp_path: Path) -> None:
    run = _coordinator(tmp_path, _SuccessfulRunner()).run_if_approved(
        route=_route(), source_chunks=[_chunk()]
    )

    assert run is not None
    assert run.timeline_execution_bundle is not None
    assert run.timeline_execution_bundle.status == TimelineExecutionStatus.SUCCEEDED
    assert run.gate3_result is not None
    assert run.gate3_result.decision == ReviewGate3Decision.APPROVED
    assert run.gate3_route is not None
    assert run.timeline_review_material is not None
    bundle_id = run.timeline_execution_bundle.bundle_id
    assert run.gate3_result.timeline_execution_bundle_id == bundle_id
    assert run.gate3_route.timeline_execution_bundle_id == bundle_id
    assert run.timeline_review_material.timeline_execution_bundle_id == bundle_id


def test_case2_schema_failure_is_reviewable_and_redacted(tmp_path: Path) -> None:
    run = _coordinator(tmp_path, _SchemaFailureRunner()).run_if_approved(
        route=_route(), source_chunks=[_chunk()]
    )

    assert run is not None
    assert run.timeline_execution_bundle is not None
    assert run.timeline_execution_bundle.status == TimelineExecutionStatus.FAILED
    assert run.timeline_execution_bundle.failed_items[0].failure_category == (
        ProviderFailureCategory.SCHEMA
    )
    assert run.gate3_result is not None
    assert run.gate3_result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    issue = run.gate3_result.issues[0]
    assert issue.failed_item_count == 1
    assert run.timeline_review_material is not None
    assert run.timeline_review_material.failure_summary is not None
    assert run.timeline_review_material.failure_summary.category == (
        ProviderFailureCategory.SCHEMA
    )
    assert run.timeline_review_material.failure_summary.field_path == (
        "temporal_relations[0].relation"
    )
    assert "raw_response" not in run.model_dump_json()
    assert "provider response is not persisted" not in run.model_dump_json()


def test_case3_timeout_is_not_a_direct_pipeline_failure(tmp_path: Path) -> None:
    run = _coordinator(tmp_path, _TimeoutRunner()).run_if_approved(
        route=_route(), source_chunks=[_chunk()]
    )

    assert run is not None
    assert run.timeline_execution_bundle is not None
    assert run.timeline_execution_bundle.status == TimelineExecutionStatus.NEEDS_HUMAN_ACTION
    assert run.timeline_execution_bundle.failed_items[0].failure_category == (
        ProviderFailureCategory.TIMEOUT
    )
    assert "TIMELINE_PROVIDER_TIMEOUT" in run.safe_issue_codes
    assert run.gate3_result is not None
    assert run.gate3_result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert run.timeline_review_material is not None


def test_case4_partial_bundle_keeps_three_candidates_and_two_failed_pairs() -> None:
    execution = _partial_bundle()
    result, route = ReviewGate3Service().review(
        project_id=execution.project_id,
        source_approved_proposal_bundle_id="gate2-bundle-1",
        timeline_run_id=execution.timeline_run_id,
        reviewer_agent_run_id="gate3-agent-partial",
        event_ids=[event.proposal_id for event in _events()],
        temporal_relations=execution.candidate_relations,
        evidence_refs=execution.evidence_refs,
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="analysis-1",
        timeline_execution_bundle=execution,
    )

    assert len(execution.candidate_relations) == 3
    assert len(execution.failed_items) == 2
    assert result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert route.route == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    issue = result.issues[-1]
    assert issue.related_pair_ids == ["pair4", "pair5"]
    assert issue.failed_item_count == 2
    assert issue.execution_failure_categories == [ProviderFailureCategory.SCHEMA]
    serialized = result.model_dump_json()
    assert "raw_response" not in serialized
    assert "Prompt" not in serialized
    assert "Authorization" not in serialized
