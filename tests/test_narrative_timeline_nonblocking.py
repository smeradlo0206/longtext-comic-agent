"""Regression coverage for non-blocking Gate 2 and Gate 3 audit material."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.review import (
    NarrativeAnalysisReviewRouteV1,
    NarrativeExecutionBundleV1,
    NarrativeExecutionProvenanceV1,
    NarrativeExecutionStatus,
    ProposalRecoveryDiagnosticV1,
    ReviewableProposalEnvelopeV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
    ReviewIssueV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
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


def _event() -> EventProposalV1:
    return EventProposalV1(
        proposal_id="event-1",
        event_type="BELL",
        summary="The bell rings.",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="bell rings")],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def _execution_bundle(
    *, candidates: list[ReviewableProposalEnvelopeV1]
) -> NarrativeExecutionBundleV1:
    evidence_refs = [
        evidence for candidate in candidates for evidence in candidate.aggregated_evidence_refs
    ]
    return NarrativeExecutionBundleV1(
        bundle_id="execution-bundle-1",
        project_id="project-1",
        document_id="document-1",
        status=NarrativeExecutionStatus.SUCCEEDED,
        candidates=candidates,
        evidence_refs=evidence_refs,
        provenance=NarrativeExecutionProvenanceV1(
            analysis_run_id="analysis-1",
            gate1_review_id="gate1-review-1",
            gate2_review_run_id="gate2-review-1",
            source_chunk_ids=["chunk-1"],
            agent_run_ids=["narrative-agent-1"],
        ),
    )


def _route(
    *,
    decision: ReviewGate2RoutingDecision,
    candidates: list[ReviewableProposalEnvelopeV1],
) -> NarrativeAnalysisReviewRouteV1:
    held = decision == ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW
    rejected = decision == ReviewGate2RoutingDecision.REJECTED
    return NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        decision=decision,
        review_status=(
            ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW if held else ReviewGate2RunStatus.COMPLETED
        ),
        total_count=1,
        approved_count=0 if (held or rejected) else 1,
        rejected_count=1 if rejected else 0,
        held_count=1 if held else 0,
        held_proposal_ids=["event-1"] if held else [],
        recovery_diagnostics=(
            [
                ProposalRecoveryDiagnosticV1(
                    proposal_id="event-1",
                    proposal_schema="EventProposalV1",
                    mode="event_extraction",
                    eligible_for_original_mode_rerun=False,
                )
            ]
            if rejected
            else []
        ),
        narrative_execution_bundle=_execution_bundle(candidates=candidates),
    )


class _Runner:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.calls = 0
        self.ambiguous = ambiguous

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        self.calls += 1
        relations = []
        if self.ambiguous:
            relations = [
                TemporalRelationProposalV1(
                    proposal_id="relation-1",
                    source_event_id="event-1",
                    target_event_id="event-2",
                    relation="UNKNOWN",
                    confidence=0,
                )
            ]
        return TimelineAnalysisProposalV1(
            proposal_id="timeline-proposal-1",
            project_id=input_context.project_id,
            temporal_relations=relations,
            evidence_refs=input_context.event_proposals[0].evidence_refs,
            confidence=0.9,
        )


class _FailingRunner:
    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        raise ProviderResponseError(
            "sanitized test failure",
            diagnostics={
                "schema_error_kind": "literal_error",
                "schema_error_field_paths": ["temporal_relations[0].relation"],
            },
        )


def _coordinator(session: Session, runner: _Runner) -> NarrativeTimelineCoordinator:
    return NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(session),
        timeline_runner=runner,
        agent_run_repository=AgentRunRepository(session),
    )


def test_gate2_needs_human_review_still_enters_timeline(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'nonblocking.db'}")
    Base.metadata.create_all(engine)
    event = _event()
    second_event = _event().model_copy(update={"proposal_id": "event-2"})
    route = _route(
        decision=ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW,
        candidates=[
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=event.evidence_refs,
            ),
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=second_event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=second_event.evidence_refs,
            ),
        ],
    )
    runner = _Runner()

    timeline_run = _coordinator(Session(engine), runner).run_if_execution_ready(
        route=route, source_chunks=[_chunk()]
    )

    assert timeline_run is not None
    assert runner.calls == 1
    assert timeline_run.timeline_input is not None
    assert timeline_run.timeline_input.source_narrative_execution_bundle_id == "execution-bundle-1"


def test_gate3_needs_human_review_still_persists_timeline_review_material(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gate3-material.db'}")
    Base.metadata.create_all(engine)
    event = _event()
    second_event = _event().model_copy(update={"proposal_id": "event-2"})
    route = _route(
        decision=ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW,
        candidates=[
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=event.evidence_refs,
            ),
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=second_event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=second_event.evidence_refs,
            ),
        ],
    )
    timeline_run = _coordinator(Session(engine), _Runner(ambiguous=True)).run_if_execution_ready(
        route=route, source_chunks=[_chunk()]
    )

    assert timeline_run is not None
    assert str(timeline_run.status) == "NEEDS_HUMAN_REVIEW"
    assert timeline_run.timeline_review_material is not None
    assert str(timeline_run.timeline_review_material.review_status) == "NEEDS_HUMAN_REVIEW"
    assert timeline_run.timeline_review_material.issues


def test_execution_bundle_timeline_failure_persists_v13_review_material(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gate3-failure-material.db'}")
    Base.metadata.create_all(engine)
    event = _event()
    route = _route(
        decision=ReviewGate2RoutingDecision.REJECTED,
        candidates=[
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=event.evidence_refs,
            )
        ],
    )

    timeline_run = _coordinator(Session(engine), _FailingRunner()).run_if_execution_ready(
        route=route,
        source_chunks=[_chunk()],
    )

    assert timeline_run is not None
    assert timeline_run.schema_version == "1.3"
    assert timeline_run.status == TimelineGate3RunStatus.FAILED
    assert timeline_run.timeline_review_material is not None
    persisted = TimelineGate3Repository(Session(engine)).get_run(timeline_run.timeline_run_id)
    assert persisted is not None
    assert persisted.timeline_review_material is not None


def test_invalid_evidence_candidate_is_removed_while_valid_candidates_enter_timeline(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'invalid-evidence.db'}")
    Base.metadata.create_all(engine)
    runner = _Runner()
    invalid_event = _event().model_copy(
        update={
            "evidence_refs": [
                EvidenceRefV1(chunk_id="chunk-1", quote_text="not present in source")
            ]
        }
    )
    valid_event = _event().model_copy(update={"proposal_id": "event-2"})
    route = _route(
        decision=ReviewGate2RoutingDecision.REJECTED,
        candidates=[
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=invalid_event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=invalid_event.evidence_refs,
            ),
            ReviewableProposalEnvelopeV1(
                mode="event_extraction",
                proposal_schema="EventProposalV1",
                proposal=valid_event,
                agent_run_ids=["narrative-agent-1"],
                aggregated_evidence_refs=valid_event.evidence_refs,
            ),
        ],
    )

    timeline_run = _coordinator(Session(engine), runner).run_if_execution_ready(
        route=route, source_chunks=[_chunk()]
    )

    assert timeline_run is not None
    assert runner.calls == 1
    assert timeline_run.timeline_input is not None
    assert [event.proposal_id for event in timeline_run.timeline_input.event_proposals] == [
        "event-2"
    ]


def test_rejected_gate2_route_retains_the_audit_issue_in_execution_material() -> None:
    issue = ReviewIssueV1(
        issue_id="issue-1",
        code=ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND,
        category=ReviewIssueCategory.EVIDENCE,
        severity=ReviewIssueSeverity.BLOCKING,
        sanitized_message="Evidence was not found.",
    )
    bundle = _execution_bundle(candidates=[]).model_copy(update={"issues": [issue]})

    assert bundle.status == NarrativeExecutionStatus.SUCCEEDED
    assert bundle.issues == [issue]
