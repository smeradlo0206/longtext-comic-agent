"""End-to-end persistence and single-call contracts for Timeline/Gate 3."""

from threading import Event, Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    EventProposalV1,
    TemporalRelationProposalV1,
)
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
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
    TimelineConflictV1,
    TimelineFailureOrigin,
    TimelineGate3RunStatus,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_timeline_coordinator import NarrativeTimelineCoordinator


def _chunk() -> SourceChunkV1:
    text = "The bell rings before assembly."
    return SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )


def _route() -> NarrativeAnalysisReviewRouteV1:
    event = EventProposalV1(
        proposal_id="event-1",
        event_type="bell",
        summary="The bell rings.",
        participant_ids=[],
        location_id=None,
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="bell rings")],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )
    item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="event_extraction",
            proposal_schema="EventProposalV1",
            proposal=event,
            agent_run_ids=["narrative-agent-1"],
            aggregated_evidence_refs=event.evidence_refs,
        ),
        review_decision_id="gate2-decision-1",
    )
    bundle = ApprovedProposalBundleV1(
        bundle_id="gate2-bundle-1",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        policy_id="gate2-policy-1",
        approved_proposals=[item],
        review_decision_ids=["gate2-decision-1"],
    )
    return NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        decision=ReviewGate2RoutingDecision.APPROVED,
        review_status=ReviewGate2RunStatus.COMPLETED,
        total_count=1,
        approved_count=1,
        rejected_count=0,
        held_count=0,
        approved_proposal_bundle=bundle,
    )


class _BlockingRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.started = Event()
        self.release = Event()

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=3)
        return TimelineAnalysisProposalV1(
            proposal_id="timeline-proposal-1",
            project_id=input_context.project_id,
            temporal_relations=[],
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=input_context.event_proposals[0].evidence_refs,
            confidence=0.9,
        )


class _RecoveryRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        self.calls += 1
        relations = (
            [
                TemporalRelationProposalV1(
                    proposal_id="invalid-relation",
                    source_event_id="event-1",
                    target_event_id="missing-event",
                    relation="BEFORE",
                    evidence_refs=input_context.event_proposals[0].evidence_refs,
                    confidence=0.9,
                )
            ]
            if self.calls == 1
            else []
        )
        return TimelineAnalysisProposalV1(
            proposal_id=f"timeline-proposal-{self.calls}",
            project_id=input_context.project_id,
            temporal_relations=relations,
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=input_context.event_proposals[0].evidence_refs,
            confidence=0.9,
        )


class _TimeoutRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise TimeoutError("synthetic provider timeout")


class _SchemaFailureRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise ProviderResponseError(
            "sanitized timeline schema failure",
            diagnostics={
                "schema_error_field_paths": ["evidence_indexes.0"],
                "schema_error_rule_codes": ["TIMELINE_EVIDENCE_INDEX_INVALID"],
                "expected_output_schema": "TimelinePairInferenceV1",
                "unsafe_response": "must not persist",
            },
        )


class _InvalidRelationProviderRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise ProviderResponseError(
            "sanitized timeline schema failure",
            diagnostics={
                "schema_error_kind": "literal_error",
                "schema_error_field_paths": ["temporal_relations[0].relation"],
                "schema_error_rule_codes": ["TIMELINE_PAIR_SCHEMA_INVALID"],
                "expected_output_schema": "TimelinePairInferenceV1",
                "raw_response": "must not persist",
            },
        )


class _LocalConstructionFailureRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        TimelineConflictV1.model_validate(
            {
                "conflict_id": "conflict-1",
                "project_id": input_context.project_id,
                "category": "CONTRADICTORY_CLAIMS",
                "summary": "safe local construction fixture",
                "affected_proposal_ids": [None],
                "evidence_refs": input_context.event_proposals[0].evidence_refs,
            }
        )
        raise AssertionError("model validation must have raised")


class _ContractFailureRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise ValueError("unsafe internal contract detail")


def _coordinator(session: Session, runner: _BlockingRunner) -> NarrativeTimelineCoordinator:
    return NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(session),
        timeline_runner=runner,
        agent_run_repository=AgentRunRepository(session),
    )


def test_two_sessions_claim_one_provider_and_resume_only_reviews(tmp_path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    first_session = Session(engine)
    second_session = Session(engine)
    runner = _BlockingRunner()
    first = _coordinator(first_session, runner)
    second = _coordinator(second_session, runner)
    route = _route()
    result: list[object] = []

    thread = Thread(
        target=lambda: result.append(
            first.run_if_approved(route=route, source_chunks=[_chunk()])
        )
    )
    thread.start()
    assert runner.started.wait(timeout=3)
    competing = second.run_if_approved(route=route, source_chunks=[_chunk()])
    assert competing is not None
    assert competing.status == TimelineGate3RunStatus.RUNNING
    assert runner.calls == 1

    runner.release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    final = TimelineGate3Repository(Session(engine)).get_by_bundle("project-1", "gate2-bundle-1")
    assert final is not None
    assert final.status == TimelineGate3RunStatus.APPROVED
    assert final.provider_request_count == 1
    assert final.timeline_execution_bundle is not None
    assert final.timeline_execution_bundle.status == "SUCCEEDED"
    assert final.timeline_execution_bundle.candidate_relations == []
    assert final.gate3_result is not None
    assert final.gate3_route is not None
    assert final.timeline_review_material is not None
    assert final.gate3_result.timeline_execution_bundle_id == (
        final.timeline_execution_bundle.bundle_id
    )
    assert final.gate3_route.timeline_execution_bundle_id == (
        final.timeline_execution_bundle.bundle_id
    )
    assert final.timeline_review_material.timeline_execution_bundle_id == (
        final.timeline_execution_bundle.bundle_id
    )
    assert runner.calls == 1
    assert len(AgentRunRepository(Session(engine)).list_agent_runs("project-1")) == 2

    restarted = _coordinator(Session(engine), runner)
    assert restarted.resume(final.timeline_run_id) is not None
    assert runner.calls == 1


@pytest.mark.parametrize(
    "decision",
    [
        ReviewGate2RoutingDecision.REJECTED,
        ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW,
        ReviewGate2RoutingDecision.FAILED,
    ],
)
def test_nonapproved_gate2_route_has_zero_timeline_provider_calls(tmp_path, decision) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    runner = _BlockingRunner()
    coordinator = _coordinator(Session(engine), runner)
    blocked = _route().model_copy(
        update={"decision": decision, "approved_proposal_bundle": None}
    )

    assert coordinator.run_if_approved(route=blocked, source_chunks=[_chunk()]) is None
    assert runner.calls == 0


def test_timeline_timeout_persists_only_safe_failure_diagnostics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=_TimeoutRunner(),
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    failed = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert failed is not None
    assert failed.status == TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW
    assert str(failed.failure_category) == "PROVIDER_TIMEOUT"
    assert failed.safe_issue_codes == ["TIMELINE_PROVIDER_TIMEOUT"]
    assert failed.timeline_review_material is not None
    assert failed.timeline_review_material.review_status == "NEEDS_HUMAN_REVIEW"
    assert failed.timeline_review_material.failure_summary is not None
    assert failed.timeline_review_material.failure_summary.category == "PROVIDER_TIMEOUT"
    assert failed.timeline_execution_bundle is not None
    assert failed.timeline_execution_bundle.status == "NEEDS_HUMAN_ACTION"
    assert (
        failed.timeline_execution_bundle.failed_items[0].failure_category
        == "PROVIDER_TIMEOUT"
    )
    assert "synthetic provider timeout" not in failed.timeline_execution_bundle.model_dump_json()
    assert failed.gate3_route is not None
    assert failed.gate3_route.held_issue_ids


def test_timeline_schema_failure_persists_only_typed_safe_diagnostics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=_SchemaFailureRunner(),
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    failed = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert failed is not None
    assert failed.status == TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW
    assert failed.provider_diagnostics is not None
    assert failed.provider_diagnostics.schema_error_field_paths == ["evidence_indexes.0"]
    assert failed.provider_diagnostics.schema_error_rule_codes == [
        "TIMELINE_EVIDENCE_INDEX_INVALID"
    ]
    assert (
        failed.provider_diagnostics.failure_origin
        == TimelineFailureOrigin.LLM_OUTPUT_SCHEMA_INVALID
    )
    assert failed.timeline_review_material is not None
    assert failed.gate3_result is not None
    assert failed.timeline_review_material.failure_summary is not None
    assert failed.timeline_review_material.failure_summary.field_path == "evidence_indexes.0"
    assert "unsafe_response" not in failed.model_dump_json()
    assert failed.timeline_execution_bundle is not None
    assert failed.timeline_execution_bundle.status == "FAILED"
    assert failed.timeline_execution_bundle.failed_items[0].field_path == "evidence_indexes.0"
    assert failed.timeline_execution_bundle.diagnostics[0].field_path == "evidence_indexes.0"
    assert failed.gate3_result is not None
    issue = failed.gate3_result.issues[0]
    assert issue.failed_item_count == 1
    assert issue.execution_diagnostic_field_paths == ["evidence_indexes.0"]
    assert "unsafe_response" not in failed.gate3_result.model_dump_json()
    assert failed.status == TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW


def test_invalid_llm_relation_records_sanitized_field_path_and_enum_category(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=_InvalidRelationProviderRunner(),
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    failed = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert failed is not None
    assert failed.provider_diagnostics is not None
    assert (
        failed.provider_diagnostics.failure_origin
        == TimelineFailureOrigin.LLM_OUTPUT_SCHEMA_INVALID
    )
    assert failed.provider_diagnostics.validation_errors[0].field_path == (
        "temporal_relations[0].relation"
    )
    assert failed.provider_diagnostics.validation_errors[0].error_type == "literal_error"
    assert failed.provider_diagnostics.validation_errors[0].message_type == "enum_error"
    assert failed.timeline_review_material is not None
    assert failed.timeline_review_material.failure_summary is not None
    assert (
        failed.timeline_review_material.failure_summary.field_path
        == "temporal_relations[0].relation"
    )
    assert "raw_response" not in failed.model_dump_json()


def test_local_timeline_construction_validation_is_diagnosed_and_materialized(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=_LocalConstructionFailureRunner(),
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    failed = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert failed is not None
    assert failed.status == TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW
    assert failed.provider_diagnostics is not None
    assert (
        failed.provider_diagnostics.failure_origin
        == TimelineFailureOrigin.LOCAL_ARTIFACT_CONSTRUCTION_ERROR
    )
    assert failed.provider_diagnostics.validation_errors[0].field_path == (
        "affected_proposal_ids[0]"
    )
    assert failed.provider_diagnostics.validation_errors[0].message_type == "type_error"
    assert failed.timeline_review_material is not None
    assert failed.timeline_review_material.failure_summary is not None
    assert (
        failed.timeline_review_material.failure_summary.error_origin
        == TimelineFailureOrigin.LOCAL_ARTIFACT_CONSTRUCTION_ERROR
    )
    persisted = TimelineGate3Repository(Session(engine)).get_run(failed.timeline_run_id)
    assert persisted is not None
    assert persisted.timeline_review_material is not None
    assert persisted.timeline_execution_bundle is not None
    assert persisted.timeline_execution_bundle.failed_items[0].failure_origin == (
        "LOCAL_ARTIFACT_CONSTRUCTION_ERROR"
    )


def test_contract_validation_failure_has_a_source_free_origin(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=_ContractFailureRunner(),
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    failed = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert failed is not None
    assert failed.provider_diagnostics is not None
    assert (
        failed.provider_diagnostics.failure_origin
        == TimelineFailureOrigin.CONTRACT_VALIDATION_ERROR
    )
    assert failed.timeline_review_material is not None
    assert failed.timeline_review_material.failure_summary is not None
    assert "unsafe internal contract detail" not in failed.model_dump_json()


def test_recovery_uses_same_approved_scope_and_preserves_rejected_artifacts(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3.db'}")
    Base.metadata.create_all(engine)
    runner = _RecoveryRunner()
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=runner,
        agent_run_repository=AgentRunRepository(Session(engine)),
    )

    rejected = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])
    assert rejected is not None
    assert rejected.status == TimelineGate3RunStatus.REJECTED
    assert rejected.approved_timeline_bundle is None
    assert rejected.timeline_review_material is not None
    assert rejected.gate3_result is not None
    assert rejected.gate3_result.issues[0].issue_code == "UNKNOWN_EVENT_REFERENCE"
    assert runner.calls == 1

    recovered = coordinator.recover(
        timeline_run_id=rejected.timeline_run_id,
        source_chunks=[_chunk()],
    )
    assert recovered is not None
    assert recovered.status == TimelineGate3RunStatus.APPROVED
    assert recovered.provider_request_count == 2
    assert recovered.initial_gate3_result is not None
    assert recovered.initial_gate3_route is not None
    assert recovered.initial_gate3_route.approved_timeline_bundle is None
    assert recovered.approved_timeline_bundle is not None
    assert recovered.recovery_budget.attempts_used == 1
    assert runner.calls == 2
    assert coordinator.recover(
        timeline_run_id=rejected.timeline_run_id,
        source_chunks=[_chunk()],
    ).provider_request_count == 2
