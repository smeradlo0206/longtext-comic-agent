"""End-to-end persistence and single-call contracts for Timeline/Gate 3."""

from threading import Event, Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
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
    TimelineAnalysisMode,
    TimelineAnalysisProposalV1,
    TimelineGate3RunStatus,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_timeline_coordinator import NarrativeTimelineCoordinator
from comic_agent.services.narrative_timeline_input_adapter import NarrativeTimelineInputAdapter


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


class _CapturingRunner:
    def __init__(self) -> None:
        self.input_context: TimelineAnalysisInputV1 | None = None

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        self.input_context = input_context
        return TimelineAnalysisProposalV1(
            proposal_id="timeline-mode-proposal",
            project_id=input_context.project_id,
            evidence_refs=input_context.event_proposals[0].evidence_refs,
            confidence=0.9,
        )


def _coordinator(session: Session, runner: _BlockingRunner) -> NarrativeTimelineCoordinator:
    return NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(session),
        timeline_runner=runner,
        agent_run_repository=AgentRunRepository(session),
    )


@pytest.mark.parametrize("mode", [TimelineAnalysisMode.LLM, TimelineAnalysisMode.RULES_ONLY])
def test_coordinator_explicitly_propagates_timeline_mode(tmp_path, mode) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / f'timeline-{mode}.db'}")
    Base.metadata.create_all(engine)
    runner = _CapturingRunner()
    coordinator = NarrativeTimelineCoordinator(
        repository=TimelineGate3Repository(Session(engine)),
        timeline_runner=runner,
        agent_run_repository=AgentRunRepository(Session(engine)),
        timeline_mode=mode,
    )

    result = coordinator.run_if_approved(route=_route(), source_chunks=[_chunk()])

    assert result is not None
    assert runner.input_context is not None
    assert runner.input_context.mode == mode
    assert result.timeline_input is not None
    assert result.timeline_input.mode == mode


def test_adapter_filters_nonfactual_modern_claims() -> None:
    route = _route()
    bundle = route.approved_proposal_bundle
    assert bundle is not None
    claim = ClaimProposalV1(
        proposal_id="claim-belief-1",
        claim_type="BELIEF",
        claim_text="Lin believes the archive is closed.",
        temporal_scope="PRESENT",
        source_type="CHARACTER",
        source_id="lin",
        verification_status="UNVERIFIED",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="bell rings")],
        confidence=0.8,
        reality_layer=RealityLayer.PRIMARY,
    )
    claim_item = ApprovedProposalItemV1(
        source=ReviewableProposalEnvelopeV1(
            mode="claim_extraction",
            proposal_schema="ClaimProposalV1",
            proposal=claim,
            agent_run_ids=["narrative-agent-claim-1"],
            aggregated_evidence_refs=claim.evidence_refs,
        ),
        review_decision_id="gate2-decision-claim-1",
    )
    route = route.model_copy(
        update={
            "approved_proposal_bundle": bundle.model_copy(
                update={"approved_proposals": [*bundle.approved_proposals, claim_item]}
            )
        }
    )

    timeline_input = NarrativeTimelineInputAdapter().build_from_approved_bundle(
        route=route,
        source_chunks=[_chunk()],
    )

    assert timeline_input.claim_proposals == []


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
