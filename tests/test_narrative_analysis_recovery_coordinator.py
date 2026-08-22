"""Behavior tests for deterministic Stage B recovery decisions."""

from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.config import Settings
from comic_agent.database.base import Base
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.recovery import (
    RecoveryAttemptStatus,
    RecoveryAttemptV1,
    RecoveryOutcomeStatus,
    RecoveryPolicyV1,
)
from comic_agent.schemas.review import (
    ProposalReviewDecision,
    ReviewCheckStatus,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    AggregatedEventProposalV1,
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunStatus,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.narrative_analysis_recovery_coordinator import (
    NarrativeAnalysisRecoveryCoordinator,
)
from comic_agent.services.narrative_analysis_review_coordinator import (
    NarrativeAnalysisReviewCoordinator,
)
from comic_agent.services.review_gate2_service import (
    ReviewGate2Service,
    ReviewGate2ServiceContext,
)
from comic_agent.workflows.narrative_analyst_workflow import NarrativeAnalystWorkflow


class _SourceRepository:
    def get_review_gate1(self, document_id: str):
        assert document_id == "document-1"
        return SimpleNamespace(
            approved_chunk_bundle=SimpleNamespace(chunk_ids=["chunk-1", "chunk-2"])
        )


class _AnalysisRepository:
    def __init__(self) -> None:
        event = EventProposalV1(
            proposal_id="event-1", event_type="DISCOVERY", summary="A discovery.",
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="not found")],
            confidence=0.8, reality_layer="PRIMARY",
        )
        self.run = NarrativeAnalysisRunV1(
            analysis_run_id="analysis-1", project_id="project-1", document_id="document-1",
            modes=["event_extraction"], status=NarrativeAnalysisRunStatus.SUCCEEDED,
        )
        self.result = NarrativeAnalysisResultV1(
            analysis_run_id="analysis-1",
            events=[AggregatedEventProposalV1(
                proposal=event, agent_run_ids=["agent-run-1"], evidence_refs=event.evidence_refs
            )],
        )
        self.windows = [NarrativeAnalysisWindowV1(
            analysis_window_id="window-1", analysis_run_id="analysis-1",
            mode="event_extraction", window_index=0, chunk_ids=["chunk-1", "chunk-2"],
            owned_chunk_ids=["chunk-1", "chunk-2"], status=NarrativeAnalysisWindowStatus.SUCCEEDED,
            agent_run_id="agent-run-1",
        )]

    def get_run(self, run_id: str):
        return self.run if run_id == self.run.analysis_run_id else None

    def get_result(self, run_id: str):
        return self.result if run_id == self.run.analysis_run_id else None

    def list_windows(self, run_id: str):
        assert run_id == self.run.analysis_run_id
        return self.windows


class _RecoveryRepository:
    def list_attempts(self, root_run_id: str):
        assert root_run_id == "analysis-1"
        return []


def _policy() -> RecoveryPolicyV1:
    return RecoveryPolicyV1(
        policy_id="policy-1",
        allowed_issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
        terminal_issue_codes=[ReviewIssueCode.EXACT_DUPLICATE, ReviewIssueCode.PROVENANCE_MISSING],
        max_attempts_per_proposal=1, max_attempts_per_window=1,
        max_attempts_per_root_run=1, max_total_tokens=100,
        max_elapsed_seconds=60, max_provider_requests=1,
    )


def test_directive_locks_original_mode_leaf_window_and_gate1_scope() -> None:
    """Changing mode/window/scope must make recovery derivation impossible."""

    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=_SourceRepository(), analysis_repository=_AnalysisRepository(),
        recovery_repository=_RecoveryRepository(), policy=_policy(),
    )

    directive = coordinator.derive_directive(
        "analysis-1", "event-1", [ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND]
    )

    assert directive.mode == "event_extraction"
    assert directive.original_window_id == "window-1"
    assert directive.ordered_source_chunk_ids == ["chunk-1", "chunk-2"]
    assert directive.approved_source_chunk_ids == ["chunk-1", "chunk-2"]
    assert directive.max_provider_calls == 1


def test_terminal_or_unknown_issue_never_creates_rerun_directive() -> None:
    """Removing explicit policy classification must stop automatic recovery."""

    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=_SourceRepository(), analysis_repository=_AnalysisRepository(),
        recovery_repository=_RecoveryRepository(), policy=_policy(),
    )

    outcome = coordinator.derive_directive(
        "analysis-1", "event-1", [ReviewIssueCode.EXACT_DUPLICATE]
    )

    assert outcome.status == RecoveryOutcomeStatus.NON_RECOVERABLE


def test_root_attempt_budget_exhaustion_blocks_directive() -> None:
    """A second root attempt must stop before it can reserve or invoke a Provider."""

    class _UsedRecoveryRepository(_RecoveryRepository):
        def list_attempts(self, root_run_id: str):
            return [object()]

    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=_SourceRepository(), analysis_repository=_AnalysisRepository(),
        recovery_repository=_UsedRecoveryRepository(), policy=_policy(),
    )

    outcome = coordinator.derive_directive(
        "analysis-1", "event-1", [ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND]
    )

    assert outcome.status == RecoveryOutcomeStatus.BUDGET_EXHAUSTED


def test_recovery_entry_records_safe_skipped_outcome_when_root_run_is_missing() -> None:
    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=_SourceRepository(), analysis_repository=_AnalysisRepository(),
        recovery_repository=_RecoveryRepository(), policy=_policy(),
    )

    outcomes = coordinator.recover_if_eligible("missing-run", real_llm_requested=False)

    assert [outcome.status for outcome in outcomes] == [RecoveryOutcomeStatus.SKIPPED]


class _EndToEndSourceRepository(_SourceRepository):
    def __init__(self) -> None:
        self.chunk = SourceChunkV1(
            chunk_id="chunk-1", project_id="project-1", document_id="document-1",
            chapter_id="chapter-1", order=0, text="A verified event happens.", checksum="safe",
        )
        self.second_chunk = self.chunk.model_copy(
            update={"chunk_id": "chunk-2", "order": 1, "text": "A second approved passage."}
        )

    def get_chunk(self, chunk_id: str):
        chunks = {self.chunk.chunk_id: self.chunk, self.second_chunk.chunk_id: self.second_chunk}
        return chunks.get(chunk_id)

    def list_document_chunks(self, document_id: str):
        assert document_id == "document-1"
        return [self.chunk, self.second_chunk]

    def list_chapters(self, project_id: str):
        assert project_id == "project-1"
        return []


class _PersistentAnalysisRepository(_AnalysisRepository):
    def save_review_gate2_artifacts(self, *, analysis_run_id: str, result, route):
        assert analysis_run_id == self.run.analysis_run_id
        self.run = self.run.model_copy(
            update={
                "schema_version": "1.1",
                "review_gate2_result": result,
                "review_gate2_route": route,
            }
        )
        return self.run


def _rejected_root(source: _EndToEndSourceRepository) -> _PersistentAnalysisRepository:
    analysis = _PersistentAnalysisRepository()
    invalid = analysis.result.events[0].proposal.model_copy(
        update={"evidence_refs": [EvidenceRefV1(chunk_id="chunk-1", quote_text="missing quote")]}
    )
    analysis.result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[AggregatedEventProposalV1(
            proposal=invalid, agent_run_ids=["agent-run-1"], evidence_refs=invalid.evidence_refs
        )],
    )
    NarrativeAnalysisReviewCoordinator(
        source_repository=source, analysis_repository=analysis  # type: ignore[arg-type]
    ).review_if_ready("analysis-1")
    assert analysis.run.review_gate2_route is not None
    assert analysis.run.review_gate2_route.decision == "REJECTED"
    return analysis


class _InterruptAfterProviderSuccess:
    """Crash injection at the durable Provider-success / Gate-2 boundary."""

    def __init__(self, repository: NarrativeAnalysisRecoveryRepository) -> None:
        self.repository = repository
        self.interrupted = False

    def list_attempts(self, root_analysis_run_id: str):
        return self.repository.list_attempts(root_analysis_run_id)

    def reserve_attempt(self, attempt):
        return self.repository.reserve_attempt(attempt)

    def save_attempt_transition(self, attempt):
        saved = self.repository.save_attempt_transition(attempt)
        if saved.status == RecoveryAttemptStatus.PROVIDER_SUCCEEDED and not self.interrupted:
            self.interrupted = True
            raise RuntimeError("simulated process interruption")
        return saved


class _CountingProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__(
            response={
                "batch_id": "fresh-event-batch",
                "events": [{
                    "proposal_id": "fresh-event-1", "event_type": "DISCOVERY",
                    "summary": "A verified event happens.", "participant_ids": [],
                    "actor_resolution_status": "UNKNOWN",
                    "evidence_refs": [
                        {"chunk_id": "chunk-1", "quote_text": "A verified event happens."}
                    ],
                    "confidence": 0.9, "reality_layer": "PRIMARY",
                }],
            }
        )
        self.calls = 0

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().structured_generate(request, output_model)


def test_provider_success_is_durable_before_gate2_and_resume_only_reviews(tmp_path) -> None:
    """A post-provider crash resumes fresh Gate 2 without a second Provider call."""

    source = _EndToEndSourceRepository()
    analysis = _PersistentAnalysisRepository()
    invalid = analysis.result.events[0].proposal.model_copy(
        update={"evidence_refs": [EvidenceRefV1(chunk_id="chunk-1", quote_text="missing quote")]}
    )
    analysis.result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[AggregatedEventProposalV1(
            proposal=invalid, agent_run_ids=["agent-run-1"], evidence_refs=invalid.evidence_refs
        )],
    )
    NarrativeAnalysisReviewCoordinator(
        source_repository=source, analysis_repository=analysis  # type: ignore[arg-type]
    ).review_if_ready("analysis-1")
    original_result = analysis.run.review_gate2_result
    original_route = analysis.run.review_gate2_route
    assert original_route is not None and original_route.decision == "REJECTED"

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'recovery-e2e.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    agent_runs = AgentRunRepository(session)
    provider = _CountingProvider()
    workflow = NarrativeAnalystWorkflow(
        settings=Settings(enable_real_llm=True), source_repository=source,
        agent_run_repository=agent_runs, provider=provider,
    )

    def rerun(directive, attempt_id):
        return workflow.run(
            project_id=directive.project_id, mode=directive.mode,
            chunk_ids=directive.ordered_source_chunk_ids, chunk_limit=2,
            max_chars_per_chunk=directive.max_chars_per_chunk, real_llm_requested=True,
            execution_nonce=attempt_id,
        ).agent_run

    durable = NarrativeAnalysisRecoveryRepository(session)
    interrupted = _InterruptAfterProviderSuccess(durable)
    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis, recovery_repository=interrupted,
        policy=_policy(), rerun_window=rerun, get_agent_run=agent_runs.get_agent_run,
    )
    try:
        coordinator.recover_if_eligible("analysis-1", real_llm_requested=True)
    except RuntimeError as exc:
        assert str(exc) == "simulated process interruption"
    else:
        raise AssertionError("expected interruption after Provider success")

    paused = durable.list_attempts("analysis-1")
    assert len(paused) == 1
    assert paused[0].status == RecoveryAttemptStatus.PROVIDER_SUCCEEDED
    assert paused[0].new_agent_run_id is not None
    assert paused[0].new_proposal_ids == ["fresh-event-1"]
    assert paused[0].fresh_review_result is None
    assert paused[0].budget_usage.provider_requests == 1
    assert provider.calls == 1

    resumed = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis,
        recovery_repository=NarrativeAnalysisRecoveryRepository(Session(engine)), policy=_policy(),
        rerun_window=rerun, get_agent_run=AgentRunRepository(Session(engine)).get_agent_run,
    ).recover_if_eligible("analysis-1", real_llm_requested=True)

    assert [item.status for item in resumed] == [RecoveryOutcomeStatus.APPROVED]
    assert provider.calls == 1
    attempts = durable.list_attempts("analysis-1")
    assert len(attempts) == 1
    assert attempts[0].status == RecoveryAttemptStatus.COMPLETED
    assert attempts[0].fresh_route is not None
    assert attempts[0].fresh_route.decision == "APPROVED"
    assert analysis.run.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert analysis.run.review_gate2_result == original_result
    assert analysis.run.review_gate2_route == original_route

    repeated = coordinator.recover_if_eligible("analysis-1", real_llm_requested=True)
    assert [item.status for item in repeated] == [RecoveryOutcomeStatus.BUDGET_EXHAUSTED]
    assert provider.calls == 1
    assert len(durable.list_attempts("analysis-1")) == 1


class _BlockingProvider(_CountingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.called = Event()
        self.release = Event()

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.called.set()
        assert self.release.wait(5)
        return super().structured_generate(request, output_model)


def test_two_independent_sessions_reserve_one_attempt_and_one_provider_call(tmp_path) -> None:
    """A RUNNING durable reservation prevents a second coordinator from invoking Provider."""

    source = _EndToEndSourceRepository()
    analysis = _PersistentAnalysisRepository()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'recovery-race.db'}")
    Base.metadata.create_all(engine)
    provider = _BlockingProvider()
    directive = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis,
        recovery_repository=_RecoveryRepository(), policy=_policy(),
    ).derive_directive("analysis-1", "event-1", [ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND])
    assert hasattr(directive, "idempotency_key")

    def coordinator_for(session: Session) -> NarrativeAnalysisRecoveryCoordinator:
        runs = AgentRunRepository(session)
        workflow = NarrativeAnalystWorkflow(
            settings=Settings(enable_real_llm=True), source_repository=source,
            agent_run_repository=runs, provider=provider,
        )
        return NarrativeAnalysisRecoveryCoordinator(
            source_repository=source, analysis_repository=analysis,
            recovery_repository=NarrativeAnalysisRecoveryRepository(session), policy=_policy(),
            rerun_window=lambda item, attempt_id: workflow.run(
                project_id=item.project_id, mode=item.mode,
                chunk_ids=item.ordered_source_chunk_ids, chunk_limit=2,
                max_chars_per_chunk=item.max_chars_per_chunk, execution_nonce=attempt_id,
                real_llm_requested=True,
            ).agent_run,
            get_agent_run=runs.get_agent_run,
        )

    first = coordinator_for(Session(engine))
    second = coordinator_for(Session(engine))
    first_outcome: list[object] = []
    thread = Thread(target=lambda: first_outcome.append(first._execute_directive(directive, True)))
    thread.start()
    assert provider.called.wait(5)
    competing = second._execute_directive(directive, True)
    assert competing.status == RecoveryOutcomeStatus.IN_PROGRESS
    provider.release.set()
    thread.join(5)
    assert not thread.is_alive()

    attempts = NarrativeAnalysisRecoveryRepository(Session(engine)).list_attempts("analysis-1")
    assert len(attempts) == 1
    assert provider.calls == 1
    assert AgentRunRepository(Session(engine)).count_agent_runs() == 1
    assert first_outcome[0].status == RecoveryOutcomeStatus.APPROVED


def test_fresh_rejected_review_stops_without_second_provider_call(tmp_path) -> None:
    """A fresh evidence rejection is stored separately and never loops automatically."""

    source = _EndToEndSourceRepository()
    analysis = _rejected_root(source)
    original = analysis.run.review_gate2_result
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh-rejected.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    runs = AgentRunRepository(session)
    provider = _CountingProvider()
    provider._response["events"][0]["evidence_refs"][0]["quote_text"] = "not in source"
    workflow = NarrativeAnalystWorkflow(
        settings=Settings(enable_real_llm=True), source_repository=source,
        agent_run_repository=runs, provider=provider,
    )
    coordinator = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis,
        recovery_repository=NarrativeAnalysisRecoveryRepository(session), policy=_policy(),
        rerun_window=lambda directive, attempt_id: workflow.run(
            project_id=directive.project_id, mode=directive.mode,
            chunk_ids=directive.ordered_source_chunk_ids, chunk_limit=2,
            max_chars_per_chunk=directive.max_chars_per_chunk, execution_nonce=attempt_id,
            real_llm_requested=True,
        ).agent_run,
        get_agent_run=runs.get_agent_run,
    )
    outcomes = coordinator.recover_if_eligible("analysis-1", real_llm_requested=True)
    attempt = NarrativeAnalysisRecoveryRepository(session).list_attempts("analysis-1")[0]

    assert [item.status for item in outcomes] == [RecoveryOutcomeStatus.REJECTED]
    assert attempt.fresh_review_result is not original
    assert attempt.fresh_route is not None and attempt.fresh_route.decision == "REJECTED"
    assert attempt.fresh_route.approved_proposal_bundle is None
    assert provider.calls == 1


class _RouteReviewService(ReviewGate2Service):
    def __init__(self, route: str) -> None:
        self.route = route
        self.contexts: list[ReviewGate2ServiceContext] = []

    def review(self, value, context):  # type: ignore[no-untyped-def]
        self.contexts.append(context)
        if self.route == "FAILED":
            return super().review(
                value,
                ReviewGate2ServiceContext(
                    source_chunks=tuple(context.source_chunks) + tuple(context.source_chunks),
                    known_agent_run_ids=context.known_agent_run_ids,
                    agent_run_analysis_run_ids=context.agent_run_analysis_run_ids,
                ),
            )
        result = super().review(value, context)
        current = result.decisions[0]
        issue = self._issue(
            value,
            (current.proposal_schema, current.proposal_id),
            ReviewIssueCode.AMBIGUOUS_ENTITY_REFERENCE,
            ReviewIssueCategory.REFERENCE,
            ReviewIssueSeverity.REVIEW_REQUIRED,
        )
        decision = result.decisions[0].model_copy(
            update={
                "decision": ProposalReviewDecision.NEEDS_HUMAN_REVIEW,
                "schema_status": ReviewCheckStatus.NEEDS_HUMAN_REVIEW,
                "issues": [issue],
            }
        )
        return result.model_copy(
            update={
                "status": ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW,
                "decisions": [decision],
                "approved_count": 0,
                "rejected_count": 0,
                "needs_human_review_count": 1,
                "approved_bundle": None,
            }
        )


def test_fresh_human_and_failed_routes_stop_without_repeat_provider(tmp_path) -> None:
    """Fresh review terminal routes retain the recovery-only audit and do not retry."""

    for expected in ("NEEDS_HUMAN_REVIEW", "FAILED"):
        source = _EndToEndSourceRepository()
        analysis = _rejected_root(source)
        original = analysis.run.review_gate2_result
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / f'{expected}.db'}")
        Base.metadata.create_all(engine)
        session = Session(engine)
        runs = AgentRunRepository(session)
        provider = _CountingProvider()
        workflow = NarrativeAnalystWorkflow(
            settings=Settings(enable_real_llm=True), source_repository=source,
            agent_run_repository=runs, provider=provider,
        )
        reviewer = _RouteReviewService(expected)
        coordinator = NarrativeAnalysisRecoveryCoordinator(
            source_repository=source, analysis_repository=analysis,
            recovery_repository=NarrativeAnalysisRecoveryRepository(session), policy=_policy(),
            rerun_window=lambda directive, attempt_id, workflow=workflow: workflow.run(
                project_id=directive.project_id, mode=directive.mode,
                chunk_ids=directive.ordered_source_chunk_ids, chunk_limit=2,
                max_chars_per_chunk=directive.max_chars_per_chunk, execution_nonce=attempt_id,
                real_llm_requested=True,
            ).agent_run,
            get_agent_run=runs.get_agent_run, review_service=reviewer,
        )
        outcomes = coordinator.recover_if_eligible("analysis-1", real_llm_requested=True)
        attempt = NarrativeAnalysisRecoveryRepository(session).list_attempts("analysis-1")[0]

        assert [str(item.status) for item in outcomes] == [expected]
        assert attempt.fresh_review_result is not original
        assert attempt.fresh_route is not None and str(attempt.fresh_route.decision) == expected
        assert attempt.fresh_route.approved_proposal_bundle is None
        assert provider.calls == 1
        assert analysis.run.status == NarrativeAnalysisRunStatus.SUCCEEDED
        assert analysis.run.review_gate2_result == original
        assert reviewer.contexts[0].known_agent_run_ids == frozenset({attempt.new_agent_run_id})
        assert tuple(chunk.chunk_id for chunk in reviewer.contexts[0].source_chunks) == (
            "chunk-1",
            "chunk-2",
        )
        repeated = coordinator.recover_if_eligible("analysis-1", real_llm_requested=True)
        assert repeated[0].status == RecoveryOutcomeStatus.BUDGET_EXHAUSTED
        assert provider.calls == 1


def test_reserved_running_and_reentrant_entries_never_claim_provider_work(tmp_path) -> None:
    """Durable RESERVED/RUNNING states win races before a recovery worker can rerun."""

    source = _EndToEndSourceRepository()
    analysis = _PersistentAnalysisRepository()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reentry.db'}")
    Base.metadata.create_all(engine)
    repository = NarrativeAnalysisRecoveryRepository(Session(engine))
    directive = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis,
        recovery_repository=_RecoveryRepository(), policy=_policy(),
    ).derive_directive("analysis-1", "event-1", [ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND])
    assert hasattr(directive, "idempotency_key")
    attempt = RecoveryAttemptV1(
        attempt_id="reserved-attempt", idempotency_key=directive.idempotency_key,
        directive=directive, status=RecoveryAttemptStatus.RESERVED,
        original_gate2_issue_codes=directive.issue_codes,
    )
    stored, _ = repository.reserve_attempt(attempt)
    calls = 0

    def forbidden_rerun(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("reserved/running attempt must not call Provider")

    reentrant = NarrativeAnalysisRecoveryCoordinator(
        source_repository=source, analysis_repository=analysis,
        recovery_repository=NarrativeAnalysisRecoveryRepository(Session(engine)), policy=_policy(),
        rerun_window=forbidden_rerun,
    )
    assert reentrant._execute_directive(directive, True).status == RecoveryOutcomeStatus.IN_PROGRESS
    running = stored.model_copy(
        update={"status": RecoveryAttemptStatus.RUNNING, "started_at": datetime.now(UTC)}
    )
    repository.save_attempt_transition(running)
    assert reentrant._execute_directive(directive, True).status == RecoveryOutcomeStatus.IN_PROGRESS
    assert calls == 0
    assert len(repository.list_attempts("analysis-1")) == 1
