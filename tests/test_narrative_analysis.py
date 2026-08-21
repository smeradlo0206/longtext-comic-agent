"""Regression tests for resumable whole-document narrative analysis."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.config import Settings
from comic_agent.database.base import Base
from comic_agent.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    KnowledgeTemporalAnchorV1,
    RelationshipSignalProposalV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    AgentRunStatus,
    NarrativeAnalysisProposalSourceV1,
    NarrativeAnalysisRunStatus,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.narrative_analysis import (
    create_narrative_analysis_run,
    plan_analysis_windows,
)
from comic_agent.services.narrative_analysis_aggregation import aggregate_narrative_analysis
from comic_agent.services.narrative_analysis_worker import NarrativeAnalysisWorker
from comic_agent.services.narrative_analyst_summary import (
    manual_review_checklist,
    recommended_action_for_failure,
)


def _chunk(order: int) -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=f"chunk-{order}",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=order,
        text=f"synthetic source {order}",
        checksum=f"checksum-{order}",
    )


def _long_chunk(order: int) -> SourceChunkV1:
    return _chunk(order).model_copy(update={"text": "Synthetic " + ("x" * 1400)})


def _relationship_signal(
    proposal_id: str,
    *,
    subject: str = "甲",
    counterpart: str = "乙",
    directionality: str = "DIRECTED",
    relationship_kind: str = "TRUSTS",
    relationship_domain: str = "TRUST",
    evidence_chunk_id: str = "chunk-0",
) -> RelationshipSignalProposalV1:
    return RelationshipSignalProposalV1.model_validate(
        {
            "proposal_id": proposal_id,
            "subject": {
                "mention_text": subject,
                "participant_kind": "CHARACTER",
                "resolution_status": "UNRESOLVED",
                "entity_proposal_id": None,
                "proposal_schema": None,
            },
            "counterpart": {
                "mention_text": counterpart,
                "participant_kind": "CHARACTER",
                "resolution_status": "UNRESOLVED",
                "entity_proposal_id": None,
                "proposal_schema": None,
            },
            "relationship_domain": relationship_domain,
            "relationship_kind": relationship_kind,
            "directionality": directionality,
            "signal_effect": "PRESENT",
            "assertion_polarity": "AFFIRMED",
            "evidence_basis": "NARRATED",
            "support_level": "EXPLICIT",
            "source_speaker": None,
            "context_event": None,
            "temporal_anchor": {
                "valid_from": None,
                "valid_until": None,
                "anchor_text": None,
                "resolution_status": "UNRESOLVED",
                "event_proposal_id": None,
                "proposal_schema": None,
            },
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": evidence_chunk_id, "quote_text": "关系证据"}],
            "confidence": 0.8,
        }
    )


def test_relationship_signal_aggregation_is_exact_and_symmetric_only_in_its_key() -> None:
    directed = _relationship_signal("relationship-1")
    directed_duplicate = _relationship_signal("relationship-2", evidence_chunk_id="chunk-1")
    reverse = _relationship_signal("relationship-3", subject="乙", counterpart="甲")
    sibling = _relationship_signal(
        "relationship-4",
        directionality="SYMMETRIC",
        relationship_kind="SIBLING_OF",
        relationship_domain="KINSHIP",
    )
    reversed_sibling = _relationship_signal(
        "relationship-5",
        subject="乙",
        counterpart="甲",
        directionality="SYMMETRIC",
        relationship_kind="SIBLING_OF",
        relationship_domain="KINSHIP",
        evidence_chunk_id="chunk-1",
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="relationship_signal_extraction", agent_run_id="run-1", proposal=directed
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="relationship_signal_extraction",
                agent_run_id="run-2",
                proposal=directed_duplicate,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="relationship_signal_extraction", agent_run_id="run-3", proposal=reverse
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="relationship_signal_extraction", agent_run_id="run-4", proposal=sibling
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="relationship_signal_extraction",
                agent_run_id="run-5",
                proposal=reversed_sibling,
            ),
        ]
    )

    assert result.schema_version == "1.5"
    assert len(result.relationship_signals) == 3
    assert result.relationship_signals[0].agent_run_ids == ["run-1", "run-2"]
    assert len(result.relationship_signals[0].evidence_refs) == 2
    assert result.relationship_signals[2].agent_run_ids == ["run-4", "run-5"]


def test_legacy_narrative_analysis_result_defaults_relationship_signals_to_empty() -> None:
    from comic_agent.schemas.workflow import NarrativeAnalysisResultV1

    result = NarrativeAnalysisResultV1.model_validate(
        {"analysis_run_id": "legacy", "events": [], "entities": [], "claims": []}
    )

    assert result.schema_version == "1.0"
    assert result.relationship_signals == []


def test_plan_analysis_windows_uses_three_chunk_windows_with_stride_two() -> None:
    windows = plan_analysis_windows([_chunk(index) for index in range(5)])

    assert [window.chunk_ids for window in windows] == [
        ["chunk-0", "chunk-1", "chunk-2"],
        ["chunk-2", "chunk-3", "chunk-4"],
    ]
    assert [window.window_index for window in windows] == [0, 1]


def test_plan_analysis_windows_assigns_each_source_chunk_one_deterministic_owner() -> None:
    windows = plan_analysis_windows([_chunk(index) for index in range(5)])

    assert [window.owned_chunk_ids for window in windows] == [
        ["chunk-0", "chunk-1", "chunk-2"],
        ["chunk-3", "chunk-4"],
    ]
    owned = [chunk_id for window in windows for chunk_id in window.owned_chunk_ids]
    assert owned == [f"chunk-{index}" for index in range(5)]
    assert all(set(window.owned_chunk_ids) <= set(window.chunk_ids) for window in windows)


def test_plan_analysis_windows_fills_stride_gaps_before_assigning_ownership() -> None:
    windows = plan_analysis_windows([_chunk(index) for index in range(5)], window_size=1, stride=3)

    owned = [chunk_id for window in windows for chunk_id in window.owned_chunk_ids]
    assert owned == [f"chunk-{index}" for index in range(5)]
    assert all(len(window.owned_chunk_ids) == 1 for window in windows)


def test_entity_manual_review_checklist_covers_creature_taxonomy_boundaries() -> None:
    checklist = manual_review_checklist("entity_extraction")

    assert checklist["creature_classification_correct"] is None
    assert checklist["creature_subtype_supported_or_null"] is None
    assert checklist["important_unnamed_objects_allowed"] is None
    assert checklist["concept_is_not_a_catch_all"] is None


@pytest.mark.parametrize(
    ("status_code", "expected_action"),
    [
        (429, "wait before resume and keep concurrency at 1"),
        (503, "wait briefly and resume failed windows"),
        (400, "check model, request shape, and response_format settings"),
        (401, "check local provider credential or access settings"),
        (403, "check local provider credential or access settings"),
        (404, "check provider endpoint and model name"),
    ],
)
def test_http_failure_recommended_actions_are_status_specific(
    status_code: int, expected_action: str
) -> None:
    assert (
        recommended_action_for_failure("PROVIDER_HTTP_ERROR", {"http_status_code": status_code})
        == expected_action
    )


def test_plan_analysis_windows_adds_a_tail_window_when_stride_would_miss_it() -> None:
    windows = plan_analysis_windows([_chunk(index) for index in range(6)])

    assert [window.chunk_ids for window in windows] == [
        ["chunk-0", "chunk-1", "chunk-2"],
        ["chunk-2", "chunk-3", "chunk-4"],
        ["chunk-3", "chunk-4", "chunk-5"],
    ]


def _repository(tmp_path: Path) -> NarrativeAnalysisRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'analysis_runs.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    return NarrativeAnalysisRepository(session)


def test_analysis_repository_persists_auditable_run_and_windows(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    run = NarrativeAnalysisRunV1(
        analysis_run_id="analysis-1",
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction", "entity_extraction"],
        status=NarrativeAnalysisRunStatus.PENDING,
        window_ids=["window-event-0", "window-entity-0"],
        created_at=created_at,
        updated_at=created_at,
    )
    windows = [
        NarrativeAnalysisWindowV1(
            analysis_window_id="window-event-0",
            analysis_run_id=run.analysis_run_id,
            mode="event_extraction",
            window_index=0,
            chunk_ids=["chunk-0", "chunk-1", "chunk-2"],
            status=NarrativeAnalysisWindowStatus.PENDING,
        ),
        NarrativeAnalysisWindowV1(
            analysis_window_id="window-entity-0",
            analysis_run_id=run.analysis_run_id,
            mode="entity_extraction",
            window_index=0,
            chunk_ids=["chunk-0", "chunk-1", "chunk-2"],
            status=NarrativeAnalysisWindowStatus.PENDING,
        ),
    ]

    repository.create_run(run, windows)

    assert repository.get_run("analysis-1") == run
    assert [window.analysis_window_id for window in repository.list_windows("analysis-1")] == [
        "window-entity-0",
        "window-event-0",
    ]


def test_window_claim_is_atomic_across_independent_sessions(tmp_path: Path) -> None:
    """Only one persisted owner may reserve a window before Provider work starts."""

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'window_claims.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    seed = NarrativeAnalysisRepository(session_factory())
    run = NarrativeAnalysisRunV1(
        analysis_run_id="analysis-claim",
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        status=NarrativeAnalysisRunStatus.PENDING,
        window_ids=["window-claim"],
    )
    window = NarrativeAnalysisWindowV1(
        analysis_window_id="window-claim",
        analysis_run_id=run.analysis_run_id,
        mode="event_extraction",
        window_index=0,
        chunk_ids=["chunk-0"],
        status=NarrativeAnalysisWindowStatus.PENDING,
        idempotency_key="stable-window-claim",
    )
    seed.create_run(run, [window])
    seed._session.close()  # type: ignore[attr-defined]

    barrier = Barrier(2)

    def claim() -> bool:
        session = session_factory()
        try:
            repository = NarrativeAnalysisRepository(session)
            barrier.wait()
            return repository.claim_window(
                window.model_copy(update={"status": NarrativeAnalysisWindowStatus.RESERVED})
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: claim(), range(2)))

    verify_session = session_factory()
    try:
        persisted = NarrativeAnalysisRepository(verify_session).list_windows(run.analysis_run_id)
    finally:
        verify_session.close()
    assert claimed.count(True) == 1
    assert persisted[0].status == NarrativeAnalysisWindowStatus.RESERVED
    assert persisted[0].idempotency_key == "stable-window-claim"


def test_parallel_worker_reentry_calls_provider_and_creates_agent_run_once(tmp_path: Path) -> None:
    """A second session must observe the reserved checkpoint, never rerun it."""

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'worker_reentry.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    source_repository = _FakeSourceRepository([_chunk(0)])
    seed_session = session_factory()
    try:
        run = create_narrative_analysis_run(
            source_repository=source_repository,
            analysis_repository=NarrativeAnalysisRepository(seed_session),
            project_id="project-1",
            document_id="document-1",
            modes=["event_extraction"],
            window_size=1,
            stride=1,
            real_llm_requested=True,
        )
    finally:
        seed_session.close()
    provider = _BlockingFakeProvider()

    def invoke_worker() -> NarrativeAnalysisRunV1:
        session = session_factory()
        try:
            return NarrativeAnalysisWorker(
                settings=Settings(_env_file=None, enable_real_llm=True),
                source_repository=source_repository,
                agent_run_repository=AgentRunRepository(session),
                analysis_repository=NarrativeAnalysisRepository(session),
                provider=provider,
            ).run_pending(run.analysis_run_id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke_worker)
        assert provider.entered.wait(timeout=5)
        second = executor.submit(invoke_worker)
        second.result(timeout=5)
        provider.release.set()
        first.result(timeout=5)

    verify_session = session_factory()
    try:
        analysis_repository = NarrativeAnalysisRepository(verify_session)
        persisted = analysis_repository.get_run(run.analysis_run_id)
        windows = analysis_repository.list_windows(run.analysis_run_id)
        agent_runs = AgentRunRepository(verify_session).list_agent_runs("project-1")
    finally:
        verify_session.close()
    assert persisted is not None
    assert persisted.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert [window.status for window in windows] == [NarrativeAnalysisWindowStatus.SUCCEEDED]
    assert provider.calls == ["event_extraction"]
    assert len(agent_runs) == 1


def test_timeout_backoff_survives_worker_restart_without_recalling_provider(tmp_path: Path) -> None:
    """A persisted retry deadline prevents duplicate calls after a worker restart."""

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retry_restart.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    source_repository = _FakeSourceRepository([_chunk(0)])
    setup_session = session_factory()
    try:
        repository = NarrativeAnalysisRepository(setup_session)
        run = create_narrative_analysis_run(
            source_repository=source_repository,
            analysis_repository=repository,
            project_id="project-1",
            document_id="document-1",
            modes=["event_extraction"],
            window_size=1,
            stride=1,
            real_llm_requested=True,
        )
        provider = _RetryingWindowProvider({1: TimeoutError("synthetic timeout")})
        first = NarrativeAnalysisWorker(
            settings=Settings(_env_file=None, enable_real_llm=True),
            source_repository=source_repository,
            agent_run_repository=_FakeAgentRunRepository(),
            analysis_repository=repository,
            provider=provider,
        ).run_pending(run.analysis_run_id)
        deferred = repository.list_windows(run.analysis_run_id)[0]
        assert first.status == NarrativeAnalysisRunStatus.RUNNING
        assert deferred.status == NarrativeAnalysisWindowStatus.FAILED
        assert deferred.next_eligible_retry_at is not None
    finally:
        setup_session.close()

    restart_session = session_factory()
    try:
        restarted_repository = NarrativeAnalysisRepository(restart_session)
        resumed = NarrativeAnalysisWorker(
            settings=Settings(_env_file=None, enable_real_llm=True),
            source_repository=source_repository,
            agent_run_repository=_FakeAgentRunRepository(),
            analysis_repository=restarted_repository,
            provider=provider,
        ).run_pending(run.analysis_run_id)
        deferred = restarted_repository.list_windows(run.analysis_run_id)[0]
    finally:
        restart_session.close()

    assert resumed.status == NarrativeAnalysisRunStatus.RUNNING
    assert provider.input_text_lengths == [len(_chunk(0).text)]
    assert deferred.next_eligible_retry_at is not None


def test_timeout_splits_only_failed_window_after_persisted_backoff(tmp_path: Path) -> None:
    """A timeout never reruns a successful sibling or bypasses its retry deadline."""

    source_repository = _FakeSourceRepository([_chunk(0), _chunk(1), _chunk(2)])
    repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        window_size=2,
        stride=2,
        real_llm_requested=True,
    )
    provider = _RetryingWindowProvider({1: TimeoutError("synthetic timeout")})
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=repository,
        provider=provider,
    )

    deferred = worker.run_pending(run.analysis_run_id)
    windows = repository.list_windows(run.analysis_run_id)
    split_parent = next(window for window in windows if window.status == "SPLIT")
    children = [
        window
        for window in windows
        if window.parent_window_id == split_parent.analysis_window_id
    ]

    assert deferred.status == NarrativeAnalysisRunStatus.RUNNING
    assert split_parent.failure_category == "PROVIDER_TIMEOUT"
    assert split_parent.provider_request_count == 1
    assert split_parent.elapsed_seconds_used >= 1
    # The independent second planned window succeeded; it must not be replayed
    # while the failed parent waits for its split recovery deadline.
    assert len(provider.input_text_lengths) == 2
    assert len(children) == 2
    assert all(child.next_eligible_retry_at is not None for child in children)
    assert all(child.split_depth == 1 and child.max_split_depth == 3 for child in children)
    assert all(child.effective_max_chars_per_chunk <= 800 for child in children)

    still_deferred = worker.run_pending(run.analysis_run_id)
    assert still_deferred.status == NarrativeAnalysisRunStatus.RUNNING
    assert len(provider.input_text_lengths) == 2

    for child in children:
        repository.save_window(
            child.model_copy(
                update={
                    "next_eligible_retry_at": datetime.now(UTC) - timedelta(seconds=1)
                }
            )
        )
    completed = worker.run_pending(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert len(provider.input_text_lengths) == 4
    assert all(
        window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
        for window in repository.list_windows(run.analysis_run_id)
        if window.parent_window_id == split_parent.analysis_window_id
    )


def test_window_budget_exhaustion_stops_before_gate2_or_timeline(tmp_path: Path) -> None:
    """A failed final Provider call is terminal and cannot make the root run succeed."""

    source_repository = _FakeSourceRepository([_chunk(0)])
    repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        window_size=1,
        stride=1,
        max_call_attempts=1,
        real_llm_requested=True,
    )
    provider = _RetryingWindowProvider({1: TimeoutError("synthetic timeout")})
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)
    window = repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.FAILED
    assert completed.review_gate2_result is None
    assert completed.review_gate2_route is None
    assert window.status == NarrativeAnalysisWindowStatus.EXHAUSTED
    assert window.failure_category == "PROVIDER_TIMEOUT"
    assert window.provider_request_count == 1
    assert window.next_eligible_retry_at is None
    assert len(provider.input_text_lengths) == 1


def test_window_diagnostics_v1_2_keeps_prior_payloads_readable() -> None:
    legacy = NarrativeAnalysisWindowV1.model_validate(
        {
            "schema_version": "1.0",
            "window_index": 0,
            "chunk_ids": ["chunk-0"],
            "analysis_window_id": "window-legacy-0",
            "analysis_run_id": "analysis-legacy",
            "mode": "event_extraction",
            "status": "FAILED",
            "error_message": "sanitized legacy failure",
        }
    )
    v1_1 = NarrativeAnalysisWindowV1.model_validate(
        {
            "schema_version": "1.1",
            "window_index": 1,
            "chunk_ids": ["chunk-1"],
            "analysis_window_id": "window-v1-1",
            "analysis_run_id": "analysis-v1-1",
            "mode": "event_extraction",
            "status": "FAILED",
            "failure_category": "PROVIDER_TIMEOUT",
        }
    )
    v1_2 = NarrativeAnalysisWindowV1.model_validate(
        {
            "schema_version": "1.2",
            "window_index": 2,
            "chunk_ids": ["chunk-2"],
            "analysis_window_id": "window-v1-2",
            "analysis_run_id": "analysis-v1-2",
            "mode": "event_extraction",
            "status": "FAILED",
        }
    )
    v1_3 = NarrativeAnalysisWindowV1.model_validate(
        {
            "schema_version": "1.3",
            "window_index": 3,
            "chunk_ids": ["chunk-3"],
            "analysis_window_id": "window-v1-3",
            "analysis_run_id": "analysis-v1-3",
            "mode": "event_extraction",
            "status": "SPLIT",
        }
    )
    current = NarrativeAnalysisWindowV1(
        analysis_window_id="window-current-0",
        analysis_run_id="analysis-current",
        mode="event_extraction",
        window_index=0,
        chunk_ids=["chunk-0"],
        status="FAILED",
        failure_category="PROVIDER_TIMEOUT",
        recommended_action="increase timeout or reduce max_chars_per_chunk",
        provider_error_diagnostics={"timeout_kind": "read"},
    )

    assert legacy.schema_version == "1.0"
    assert legacy.failure_category is None
    assert legacy.owned_chunk_ids == ["chunk-0"]
    assert v1_1.schema_version == "1.1"
    assert v1_1.attempt_count == 0
    assert v1_2.schema_version == "1.2"
    assert v1_3.schema_version == "1.3"
    assert current.schema_version == "1.9"
    assert current.owned_chunk_ids == ["chunk-0"]
    assert current.provider_error_diagnostics == {"timeout_kind": "read"}


def test_analysis_tables_are_added_without_rewriting_existing_sqlite_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'existing.db'}", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE legacy_imports (record_id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO legacy_imports (record_id) VALUES ('legacy-1')"))

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "narrative_analysis_runs" in inspector.get_table_names()
    assert "narrative_analysis_windows" in inspector.get_table_names()
    with engine.connect() as connection:
        record_id = connection.execute(text("SELECT record_id FROM legacy_imports")).scalar_one()
    assert record_id == "legacy-1"


class _FakeSourceRepository:
    def __init__(self, chunks: list[SourceChunkV1]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def list_document_chunks(self, document_id: str) -> list[SourceChunkV1]:
        return [chunk for chunk in self._chunks.values() if chunk.document_id == document_id]

    def list_project_chunks(self, project_id: str) -> list[SourceChunkV1]:
        return [chunk for chunk in self._chunks.values() if chunk.project_id == project_id]

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        return self._chunks.get(chunk_id)

    def list_chapters(self, project_id: str) -> list[object]:
        return []


def test_analysis_run_idempotency_keeps_dry_run_and_real_opt_in_separate(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])

    dry_run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=False,
    )
    real_opt_in = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )

    assert dry_run.analysis_run_id != real_opt_in.analysis_run_id
    assert dry_run.real_llm_requested is False
    assert real_opt_in.real_llm_requested is True


def test_long_document_plan_persists_stable_budgeted_batch_manifests(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    repository = _repository(tmp_path)

    first = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        window_size=2,
        stride=1,
        batch_max_chunks=2,
        output_token_budget=321,
        time_budget_seconds=45,
        max_call_attempts=2,
    )
    second = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        window_size=2,
        stride=1,
        batch_max_chunks=2,
        output_token_budget=321,
        time_budget_seconds=45,
        max_call_attempts=2,
    )
    windows = repository.list_windows(first.analysis_run_id)

    assert second.analysis_run_id == first.analysis_run_id
    assert [batch.chunk_ids for batch in first.batches] == [
        ["chunk-0", "chunk-1"],
        ["chunk-2", "chunk-3"],
        ["chunk-4"],
    ]
    assert all(batch.estimated_input_chars > 0 for batch in first.batches)
    assert all(batch.estimated_input_tokens > 0 for batch in first.batches)
    assert all(batch.output_token_budget == 321 for batch in first.batches)
    assert all(window.batch_id in {batch.batch_id for batch in first.batches} for window in windows)
    assert all(window.max_call_attempts == 2 for window in windows)
    assert all(window.time_budget_seconds == 45 for window in windows)


class _FakeAgentRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, object] = {}

    def save_agent_run(self, agent_run):  # type: ignore[no-untyped-def]
        self.runs[agent_run.agent_run_id] = agent_run
        return agent_run

    def get_agent_run(self, agent_run_id: str):  # type: ignore[no-untyped-def]
        return self.runs.get(agent_run_id)


class _FakeProvider:
    def __init__(self, *, fail_entity_once: bool = False) -> None:
        self.calls: list[str] = []
        self.invocations: list[tuple[str, list[str]]] = []
        self.fail_entity_once = fail_entity_once

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        mode_prompt = str(request["system_prompt"])
        mode = (
            "entity_extraction"
            if "EntityExtractionAgent" in mode_prompt
            else "event_extraction"
            if "EventExtractionAgent" in mode_prompt
            else "claim_extraction"
        )
        input_context = request["input_context"]
        self.invocations.append((mode, list(input_context["source_chunk_ids"])))
        if "EntityExtractionAgent" in mode_prompt and self.fail_entity_once:
            self.fail_entity_once = False
            raise TimeoutError("synthetic provider timeout")
        self.calls.append(mode)
        chunk_id = input_context["source_chunk_ids"][0]
        quote = input_context["source_chunks"][0]["text"][:4]
        if mode == "event_extraction":
            return output_model.model_validate(
                {
                    "batch_id": f"event-batch-{chunk_id}",
                    "events": [
                        {
                            "proposal_id": f"event-{chunk_id}",
                            "event_type": "action",
                            "summary": "synthetic action",
                            "participant_ids": [],
                            "actor_resolution_status": "UNKNOWN",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "confidence": 0.8,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )
        if mode == "claim_extraction":
            return output_model.model_validate(
                {
                    "batch_id": f"claim-batch-{chunk_id}",
                    "claims": [
                        {
                            "proposal_id": f"claim-{chunk_id}",
                            "claim_type": "FACTUAL_ASSERTION",
                            "claim_text": "Synthetic gate status.",
                            "temporal_scope": "PRESENT",
                            "source_type": "NARRATOR",
                            "verification_status": "UNVERIFIED",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "confidence": 0.8,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )
        return output_model.model_validate(
            {
                "batch_id": f"entity-batch-{chunk_id}",
                "entities": [
                    {
                        "proposal_id": f"entity-{chunk_id}",
                        "entity_type": "CREATURE",
                        "creature_subtype": None,
                        "canonical_name": "Synthetic creature",
                        "aliases": [],
                        "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                        "confidence": 0.8,
                    }
                ],
            }
        )


class _EmptyEventProvider(_FakeProvider):
    """Return a valid empty Event batch for a scope without an auditable event."""

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        mode_prompt = str(request["system_prompt"])
        if "EventExtractionAgent" not in mode_prompt:
            return super().structured_generate(request, output_model)
        input_context = request["input_context"]
        assert isinstance(input_context, dict)
        source_chunk_ids = input_context["source_chunk_ids"]
        assert isinstance(source_chunk_ids, list)
        self.calls.append("event_extraction")
        return output_model.model_validate(
            {"batch_id": f"event-batch-{source_chunk_ids[0]}", "events": []}
        )


class _BlockingFakeProvider(_FakeProvider):
    """Keep the winning worker inside its Provider call for re-entry coverage."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().structured_generate(request, output_model)


class _FailSecondWindowProvider(_FakeProvider):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        if self.calls:
            raise self._error
        return super().structured_generate(request, output_model)


class _RetryingWindowProvider(_FakeProvider):
    def __init__(self, failures: dict[int, BaseException]) -> None:
        super().__init__()
        self._failures = failures
        self.input_text_lengths: list[int] = []
        self.output_recovery_markers: list[str | None] = []

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        input_context = request["input_context"]
        assert isinstance(input_context, dict)
        output_recovery = input_context.get("output_recovery")
        assert output_recovery is None or isinstance(output_recovery, str)
        self.output_recovery_markers.append(output_recovery)
        source_chunks = input_context["source_chunks"]
        assert isinstance(source_chunks, list)
        first_chunk = source_chunks[0]
        assert isinstance(first_chunk, dict)
        text = first_chunk["text"]
        assert isinstance(text, str)
        self.input_text_lengths.append(len(text))
        failure = self._failures.get(len(self.input_text_lengths))
        if failure is not None:
            raise failure
        return super().structured_generate(request, output_model)


class _BoundaryLengthProvider(_FakeProvider):
    """Fail broad windows and accept source-chunk-bounded recovery calls."""

    def __init__(self) -> None:
        super().__init__()
        self.input_chunk_ids: list[list[str]] = []
        self.input_texts: list[list[str]] = []

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        input_context = request["input_context"]
        chunk_ids = list(input_context["source_chunk_ids"])
        chunks = input_context["source_chunks"]
        self.input_chunk_ids.append(chunk_ids)
        self.input_texts.append([chunk["text"] for chunk in chunks])
        if len(chunk_ids) > 1:
            raise ProviderResponseError(
                "LLM provider response exceeded max output tokens before final content",
                {"finish_reason": "length", "content_type": "NoneType"},
            )
        return super().structured_generate(request, output_model)


class _OwnershipBoundaryProvider:
    """Return one auditable change per selected chunk and fail the overlap parent."""

    def __init__(self, *, fail_second: bool = True, distinct_overlap: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail_second = fail_second
        self.distinct_overlap = distinct_overlap

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        input_context = request["input_context"]
        chunk_ids = list(input_context["source_chunk_ids"])
        self.calls.append(chunk_ids)
        if self.fail_second and len(self.calls) == 2 and len(chunk_ids) > 1:
            raise ProviderResponseError(
                "LLM provider response exceeded max output tokens before final content",
                {"finish_reason": "length", "content_type": "NoneType"},
            )
        changes = []
        for chunk in input_context["source_chunks"]:
            chunk_id = chunk["chunk_id"]
            quote = chunk["text"][:4]
            changes.append(
                {
                    "schema_version": "1.3",
                    "proposal_id": f"ownership-{chunk_id}",
                    "event": {
                        "event_summary": (
                            f"change-{chunk_id}-call-{len(self.calls)}"
                            if self.distinct_overlap
                            else f"change-{chunk_id}"
                        ),
                        "event_proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "mention_text": quote,
                        "target_kind": "OBJECT",
                        "entity_proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "attribute_path": "accessibility",
                    "old_value": None,
                    "new_value": "closed",
                    "persistent": False,
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                    "new_value_evidence_indexes": [0],
                    "persistence_evidence_indexes": [],
                    "confidence": 0.8,
                }
            )
        return output_model.model_validate(
            {
                "schema_version": "1.3",
                "batch_id": f"ownership-batch-{len(self.calls)}",
                "changes": changes,
            }
        )


class _KnowledgeStateWindowProvider:
    def __init__(self, *, empty: bool = False, multiple: bool = False) -> None:
        self.calls: list[str] = []
        self.empty = empty
        self.multiple = multiple

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls.append("knowledge_state_extraction")
        input_context = request["input_context"]
        chunk_id = input_context["source_chunk_ids"][0]
        quote = input_context["source_chunks"][0]["text"][:4]
        states = []
        if not self.empty:
            states = [
                {
                    "schema_version": "1.1",
                    "proposal_id": f"knowledge-{chunk_id}",
                    "subject": {
                        "mention_text": "Synthetic subject",
                        "entity_proposal_id": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "target_kind": "WORLD_FACT",
                        "target_text": "Synthetic fact",
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "epistemic_status": "SUSPECTS",
                    "epistemic_basis": "INFERRED",
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                    "confidence": 0.8,
                }
            ]
            if self.multiple:
                states.append(
                    states[0]
                    | {
                        "proposal_id": f"knowledge-belief-{chunk_id}",
                        "epistemic_status": "BELIEVES",
                        "epistemic_basis": "OBSERVED",
                    }
                )
        return output_model.model_validate(
            {"batch_id": f"knowledge-batch-{chunk_id}", "states": states}
        )


class _StateChangeWindowProvider:
    def __init__(
        self,
        *,
        empty: bool = False,
        failures: dict[int, Exception] | None = None,
        invalid_evidence: bool = False,
        invalid_evidence_quote: bool = False,
        repair_evidence_on_retry: bool = False,
        mismatched_evidence_offsets: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.empty = empty
        self.failures = failures or {}
        self.invalid_evidence = invalid_evidence
        self.invalid_evidence_quote = invalid_evidence_quote
        self.repair_evidence_on_retry = repair_evidence_on_retry
        self.mismatched_evidence_offsets = mismatched_evidence_offsets
        self.output_recovery_markers: list[str | None] = []

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls.append("state_change_extraction")
        failure = self.failures.get(len(self.calls))
        if failure is not None:
            raise failure
        input_context = request["input_context"]
        self.output_recovery_markers.append(input_context.get("output_recovery"))
        chunk_id = input_context["source_chunk_ids"][0]
        quote = input_context["source_chunks"][0]["text"][:4]
        evidence_chunk_id = "unselected-chunk" if self.invalid_evidence else chunk_id
        evidence_quote = (
            "not verbatim source evidence"
            if self.invalid_evidence_quote
            and not (self.repair_evidence_on_retry and len(self.calls) > 1)
            else quote
        )
        changes = []
        if not self.empty:
            changes = [
                {
                    "schema_version": "1.2",
                    "proposal_id": f"state-change-{chunk_id}",
                    "event": {
                        "event_summary": "Synthetic gate closes",
                        "event_proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "mention_text": quote,
                        "target_kind": "OBJECT",
                        "entity_proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "attribute_path": "accessibility",
                    "old_value": None,
                    "new_value": "closed",
                    "persistent": False,
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {
                            "chunk_id": evidence_chunk_id,
                            "quote_start": 1 if self.mismatched_evidence_offsets else None,
                            "quote_end": 5 if self.mismatched_evidence_offsets else None,
                            "quote_text": evidence_quote,
                        }
                    ],
                    "new_value_evidence_indexes": [0],
                    "persistence_evidence_indexes": [],
                    "confidence": 0.8,
                }
            ]
        return output_model.model_validate(
            {
                "schema_version": "1.2",
                "batch_id": f"state-change-batch-{chunk_id}",
                "changes": changes,
            }
        )


class _RelationshipSignalWindowProvider:
    def __init__(
        self,
        *,
        empty: bool = False,
        failures: dict[int, Exception] | None = None,
        invalid_evidence_chunk: bool = False,
        mismatched_evidence_offsets: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.output_recovery_markers: list[str | None] = []
        self.empty = empty
        self.failures = failures or {}
        self.invalid_evidence_chunk = invalid_evidence_chunk
        self.mismatched_evidence_offsets = mismatched_evidence_offsets

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        input_context = request["input_context"]
        chunk_ids = input_context["source_chunk_ids"]
        self.calls.append(chunk_ids)
        self.output_recovery_markers.append(input_context.get("output_recovery"))
        failure = self.failures.get(len(self.calls))
        if failure is not None:
            raise failure
        signals = []
        if not self.empty:
            signals = [
                {
                    "proposal_id": f"relationship-{chunk_ids[0]}",
                    "subject": {
                        "mention_text": "甲",
                        "participant_kind": "CHARACTER",
                        "resolution_status": "UNRESOLVED",
                        "entity_proposal_id": None,
                        "proposal_schema": None,
                    },
                    "counterpart": {
                        "mention_text": "乙",
                        "participant_kind": "CHARACTER",
                        "resolution_status": "UNRESOLVED",
                        "entity_proposal_id": None,
                        "proposal_schema": None,
                    },
                    "relationship_domain": "TRUST",
                    "relationship_kind": "TRUSTS",
                    "directionality": "DIRECTED",
                    "signal_effect": "PRESENT",
                    "assertion_polarity": "AFFIRMED",
                    "evidence_basis": "NARRATED",
                    "support_level": "EXPLICIT",
                    "source_speaker": None,
                    "context_event": None,
                    "temporal_anchor": {
                        "valid_from": None,
                        "valid_until": None,
                        "anchor_text": None,
                        "resolution_status": "UNRESOLVED",
                        "event_proposal_id": None,
                        "proposal_schema": None,
                    },
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {
                            "chunk_id": (
                                "unselected-chunk"
                                if self.invalid_evidence_chunk
                                else chunk_ids[0]
                            ),
                            "quote_start": 1 if self.mismatched_evidence_offsets else None,
                            "quote_end": 5 if self.mismatched_evidence_offsets else None,
                            "quote_text": "甲信任乙。",
                        }
                    ],
                    "confidence": 0.8,
                }
            ]
        return output_model.model_validate(
            {
                "schema_version": "1.0",
                "batch_id": f"relationship-batch-{chunk_ids[0]}",
                "signals": signals,
            }
        )


class _StateChangeQuantityRecoveryProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.output_recovery_markers: list[str | None] = []
        self.rule_codes: list[object] = []
        self.recovery_rule_codes: list[object] = []

    def _change(
        self,
        *,
        proposal_id: str,
        target: str,
        old_value: object,
        new_value: object,
        quote: str,
        path: str = "possession.holder",
    ) -> dict[str, object]:
        return {
            "schema_version": "1.3",
            "proposal_id": proposal_id,
            "event": {
                "event_summary": quote,
                "event_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "mention_text": "卷轴" if path == "possession.holder" else "药瓶",
                "target_kind": "OBJECT",
                "entity_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": path,
            "old_value": old_value,
            "new_value": new_value,
            "persistent": False,
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-0", "quote_text": quote}],
            "new_value_evidence_indexes": [0],
            "persistence_evidence_indexes": [],
            "confidence": 0.9,
        }

    def _payload(self, *, invalid_quantity: bool) -> dict[str, object]:
        return {
            "schema_version": "1.3",
            "batch_id": "state-change-recovery-batch",
            "changes": [
                self._change(
                    proposal_id="scroll-1",
                    target="周砚",
                    old_value="阿葵",
                    new_value="周砚",
                    quote="阿葵把卷轴交给周砚",
                ),
                self._change(
                    proposal_id="scroll-2",
                    target="沈策",
                    old_value="周砚",
                    new_value="沈策",
                    quote="周砚又把卷轴交给沈策",
                ),
                self._change(
                    proposal_id="scroll-3",
                    target="陆衡",
                    old_value="沈策",
                    new_value="陆衡",
                    quote="沈策再交给陆衡",
                ),
                self._change(
                    proposal_id="medicine-quantity",
                    target="药瓶",
                    old_value=6 if not invalid_quantity else "6",
                    new_value=4 if not invalid_quantity else "4",
                    quote="药瓶数量从六变为四",
                    path="quantity",
                ),
            ],
        }

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        input_context = request["input_context"]
        self.output_recovery_markers.append(input_context.get("output_recovery"))
        if self.calls > 1:
            self.recovery_rule_codes = list(input_context.get("schema_error_rule_codes", []))
        if self.calls == 1:
            try:
                output_model.model_validate(self._payload(invalid_quantity=True))
            except ValidationError as exc:
                diagnostics = OpenAICompatibleLLMProvider.schema_validation_diagnostics(
                    exc, output_model
                )
                self.rule_codes = list(diagnostics.get("schema_error_rule_codes", []))
                raise ProviderResponseError(
                    "LLM provider response failed schema validation",
                    diagnostics,
                ) from exc
        return output_model.model_validate(self._payload(invalid_quantity=False))


@pytest.mark.parametrize(
    ("error", "expected_category", "expected_diagnostics"),
    [
        (
            ProviderTimeoutError(
                "LLM provider timeout",
                {"timeout_kind": "read", "timeout_seconds": 60},
            ),
            "PROVIDER_TIMEOUT",
            {"timeout_kind": "read", "timeout_seconds": 60},
        ),
        (
            ProviderResponseError(
                "LLM provider response exceeded max output tokens before final content",
                {"finish_reason": "length", "content_type": "NoneType"},
            ),
            "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT",
            {"finish_reason": "length", "content_type": "NoneType"},
        ),
        (
            ProviderResponseError(
                "LLM provider response content is missing",
                {"content_type": "NoneType", "has_reasoning_content": True},
            ),
            "PROVIDER_CONTENT_MISSING",
            {"content_type": "NoneType", "has_reasoning_content": True},
        ),
        (RuntimeError("unexpected synthetic source 2"), "UNKNOWN_ERROR", None),
    ],
)
def test_worker_persists_sanitized_workflow_failure_details(
    tmp_path: Path,
    error: BaseException,
    expected_category: str,
    expected_diagnostics: dict[str, object] | None,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=_FailSecondWindowProvider(error),
    )

    completed = worker.run_pending(run.analysis_run_id)
    windows = analysis_repository.list_windows(run.analysis_run_id)
    failed_window = next(
        window
        for window in windows
        if window.status
        in {NarrativeAnalysisWindowStatus.FAILED, NarrativeAnalysisWindowStatus.SPLIT}
    )
    result = analysis_repository.get_result(run.analysis_run_id)

    if expected_category == "PROVIDER_TIMEOUT":
        assert completed.status == NarrativeAnalysisRunStatus.RUNNING
        deferred_children = [
            window
            for window in windows
            if window.parent_window_id == failed_window.analysis_window_id
        ]
        assert deferred_children
        assert all(window.next_eligible_retry_at is not None for window in deferred_children)
        assert result is None
    else:
        assert completed.status == NarrativeAnalysisRunStatus.PARTIAL_FAILED
        assert result is None
    assert failed_window.failure_category == expected_category
    assert failed_window.recommended_action is not None
    assert failed_window.provider_error_diagnostics == expected_diagnostics
    assert "synthetic source" not in (failed_window.error_message or "")


class _FailingAgentRunRepository(_FakeAgentRunRepository):
    def save_agent_run(self, agent_run):  # type: ignore[no-untyped-def]
        raise RuntimeError("worker persistence failed near synthetic source 0")


def test_worker_exception_is_sanitized_and_not_replaced_with_a_fixed_message(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FailingAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=_FakeProvider(),
    )

    completed = worker.run_pending(run.analysis_run_id)
    window = analysis_repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.FAILED
    assert window.failure_category == "UNKNOWN_ERROR"
    assert window.error_message == "worker persistence failed near [redacted-source-text]"
    assert window.error_message != "Narrative analysis window failed"


def test_worker_dry_run_completes_windows_without_provider_or_source_text(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
    )
    provider = _FakeProvider()
    agent_run_repository = _FakeAgentRunRepository()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == []
    assert agent_run_repository.runs == {}
    assert result is not None
    assert result.events == []
    assert "synthetic source" not in json.dumps(completed.model_dump(mode="json"))


@pytest.mark.parametrize("empty", [False, True])
def test_relationship_signal_worker_treats_owned_or_empty_batches_as_success(
    tmp_path: Path,
    empty: bool,
) -> None:
    chunks = [
        _chunk(index).model_copy(update={"text": "甲信任乙。"}) for index in range(5)
    ]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["relationship_signal_extraction"],
        real_llm_requested=True,
    )
    provider = _RelationshipSignalWindowProvider(empty=empty)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert result is not None
    assert all(
        window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
        for window in analysis_repository.list_windows(run.analysis_run_id)
    )
    if empty:
        assert result.relationship_signals == []
    else:
        assert len(result.relationship_signals) == 1
        assert result.relationship_signals[0].proposal.relationship_kind == "TRUSTS"
        assert provider.calls == [
            ["chunk-0", "chunk-1", "chunk-2"],
            ["chunk-2", "chunk-3", "chunk-4"],
        ]


def test_relationship_signal_worker_reuses_schema_recovery_and_resume(tmp_path: Path) -> None:
    chunks = [
        _chunk(index).model_copy(update={"text": "甲信任乙。"}) for index in range(3)
    ]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["relationship_signal_extraction"],
        real_llm_requested=True,
    )
    provider = _RelationshipSignalWindowProvider(
        failures={
            1: ProviderResponseError(
                "LLM provider response failed schema validation",
                {"schema_error_kind": "missing", "schema_error_field_paths": ["signals.0"]},
            )
        }
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    calls_before_resume = len(provider.calls)
    resumed = worker.run_pending(run.analysis_run_id)
    window = analysis_repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert resumed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert window.attempt_count == 2
    assert provider.output_recovery_markers == [None, "schema_validation"]
    assert len(provider.calls) == calls_before_resume


def test_relationship_signal_worker_normalizes_verbatim_evidence_offsets(
    tmp_path: Path,
) -> None:
    chunks = [_chunk(0).model_copy(update={"text": "甲信任乙。"})]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["relationship_signal_extraction"],
        real_llm_requested=True,
    )
    provider = _RelationshipSignalWindowProvider(mismatched_evidence_offsets=True)
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert result is not None
    evidence = result.relationship_signals[0].proposal.evidence_refs[0]
    assert evidence.quote_text == "甲信任乙。"
    assert evidence.quote_start == 0
    assert evidence.quote_end == 5


def test_relationship_signal_worker_rebinds_unique_verbatim_evidence_chunk(
    tmp_path: Path,
) -> None:
    chunks = [_chunk(0).model_copy(update={"text": "甲信任乙。"})]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["relationship_signal_extraction"],
        real_llm_requested=True,
    )
    provider = _RelationshipSignalWindowProvider(invalid_evidence_chunk=True)
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert result is not None
    assert result.relationship_signals[0].proposal.evidence_refs[0].chunk_id == chunks[0].chunk_id


def test_relationship_signal_worker_splits_length_failure_by_owned_chunks(tmp_path: Path) -> None:
    chunks = [
        _chunk(index).model_copy(update={"text": "甲信任乙。"}) for index in range(3)
    ]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["relationship_signal_extraction"],
        real_llm_requested=True,
    )
    provider = _RelationshipSignalWindowProvider(
        failures={
            1: ProviderResponseError(
                "LLM provider response exceeded max output tokens before final content",
                {"finish_reason": "length", "content_type": "NoneType"},
            )
        }
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    windows = analysis_repository.list_windows(run.analysis_run_id)
    parent = next(
        window for window in windows if window.status == NarrativeAnalysisWindowStatus.SPLIT
    )
    children = [
        window for window in windows if window.parent_window_id == parent.analysis_window_id
    ]

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert parent.owned_chunk_ids == ["chunk-0", "chunk-1", "chunk-2"]
    assert [child.owned_chunk_ids for child in children] == [
        ["chunk-0"],
        ["chunk-1"],
        ["chunk-2"],
    ]
    assert provider.output_recovery_markers == [
        None,
        "length_reduction",
        "length_reduction",
        "length_reduction",
    ]


def test_worker_classifies_disabled_real_llm_without_calling_provider(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    provider = _FakeProvider()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=False),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    window = analysis_repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.FAILED
    assert provider.calls == []
    assert window.failure_category == "REAL_LLM_DISABLED"
    assert window.recommended_action == "restart the API with ENABLE_REAL_LLM=true"


def test_worker_splits_length_failure_without_truncating_child_source(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    provider = _RetryingWindowProvider(
        {
            2: ProviderResponseError(
                "LLM provider response exceeded max output tokens before final content",
                {"finish_reason": "length", "content_type": "NoneType"},
            )
        }
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    windows = analysis_repository.list_windows(run.analysis_run_id)
    retried_window = next(window for window in windows if window.window_index == 1)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.input_text_lengths == [1200, 1200, 800, 800]
    assert provider.output_recovery_markers == [
        None,
        None,
        "length_reduction",
        "length_reduction",
    ]
    assert retried_window.status == NarrativeAnalysisWindowStatus.SPLIT
    assert retried_window.attempt_count == 1
    assert retried_window.effective_max_chars_per_chunk == 1200
    assert retried_window.previous_failure_category is None
    assert all(
        window.effective_max_chars_per_chunk <= 800
        for window in windows
        if window.analysis_window_id.startswith(f"{retried_window.analysis_window_id}:split:")
    )


def test_worker_splits_length_failed_window_at_source_chunk_boundaries(
    tmp_path: Path,
) -> None:
    source_chunks = [_long_chunk(index) for index in range(3)]
    source_repository = _FakeSourceRepository(source_chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    provider = _BoundaryLengthProvider()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    windows = analysis_repository.list_windows(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.input_chunk_ids[0] == ["chunk-0", "chunk-1", "chunk-2"]
    assert provider.input_chunk_ids[1:] == [["chunk-0"], ["chunk-1"], ["chunk-2"]]
    assert [len(texts[0]) for texts in provider.input_texts[1:]] == [800, 800, 800]
    split_windows = [
        window for window in windows if window.status == NarrativeAnalysisWindowStatus.SPLIT
    ]
    succeeded_chunks = [
        window.chunk_ids
        for window in windows
        if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
    ]
    assert len(split_windows) == 1
    assert split_windows[0].owned_chunk_ids == ["chunk-0", "chunk-1", "chunk-2"]
    assert [
        window.analysis_window_id
        for window in windows
        if window.analysis_window_id.startswith(f"{split_windows[0].analysis_window_id}:split:")
    ] == [
        f"{split_windows[0].analysis_window_id}:split:0",
        f"{split_windows[0].analysis_window_id}:split:1",
        f"{split_windows[0].analysis_window_id}:split:2",
    ]
    assert succeeded_chunks == [
        ["chunk-0"],
        ["chunk-1"],
        ["chunk-2"],
    ]
    child_windows = [
        window
        for window in windows
        if window.parent_window_id == split_windows[0].analysis_window_id
    ]
    assert [window.owned_chunk_ids for window in child_windows] == [
        ["chunk-0"],
        ["chunk-1"],
        ["chunk-2"],
    ]
    assert all(
        window.split_reason == "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT"
        for window in child_windows
    )

    call_count = len(provider.input_chunk_ids)
    resumed = worker.run_pending(run.analysis_run_id)
    assert resumed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert len(provider.input_chunk_ids) == call_count


def test_split_children_only_process_parent_owned_overlap_chunks(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _OwnershipBoundaryProvider()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    windows = analysis_repository.list_windows(run.analysis_run_id)
    split_parent = next(
        window for window in windows if window.status == NarrativeAnalysisWindowStatus.SPLIT
    )

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == [
        ["chunk-0", "chunk-1", "chunk-2"],
        ["chunk-2", "chunk-3", "chunk-4"],
        ["chunk-3"],
        ["chunk-4"],
    ]
    children = [
        window for window in windows if window.parent_window_id == split_parent.analysis_window_id
    ]
    assert [child.owned_chunk_ids for child in children] == [["chunk-3"], ["chunk-4"]]
    result = analysis_repository.get_result(run.analysis_run_id)
    assert result is not None
    assert {item.proposal.event.event_summary for item in result.state_changes} == {
        "change-chunk-0",
        "change-chunk-1",
        "change-chunk-2",
        "change-chunk-3",
        "change-chunk-4",
    }


def test_state_change_aggregation_filters_non_owned_overlap_proposals(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _OwnershipBoundaryProvider(fail_second=False, distinct_overlap=True)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == [
        ["chunk-0", "chunk-1", "chunk-2"],
        ["chunk-2", "chunk-3", "chunk-4"],
    ]
    assert result is not None
    assert len(result.state_changes) == 5
    assert "change-chunk-2-call-2" not in {
        item.proposal.event.event_summary for item in result.state_changes
    }


def test_worker_splits_length_failure_and_preserves_successful_aggregate(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    length_failure = ProviderResponseError(
        "LLM provider response exceeded max output tokens before final content",
        {"finish_reason": "length", "content_type": "NoneType"},
    )
    provider = _RetryingWindowProvider({2: length_failure, 3: length_failure})
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)
    split_window = next(
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.window_index == 1
    )

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.input_text_lengths == [1200, 1200, 800, 800, 800]
    assert split_window.status == NarrativeAnalysisWindowStatus.SPLIT
    assert split_window.attempt_count == 1
    assert split_window.failure_category == "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT"
    child_windows = [
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.analysis_window_id.startswith(f"{split_window.analysis_window_id}:split:")
    ]
    assert [window.status for window in child_windows] == [
        NarrativeAnalysisWindowStatus.SUCCEEDED,
        NarrativeAnalysisWindowStatus.SUCCEEDED,
    ]
    assert result is not None
    assert len(result.events) == 3


def test_worker_retries_schema_failure_once_without_reducing_input_budget(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    provider = _RetryingWindowProvider(
        {
            2: ProviderResponseError(
                "LLM provider response failed schema validation",
                {
                    "schema_error_kind": "missing",
                    "schema_error_field_paths": ["events.0.summary"],
                    "expected_output_schema": "EventProposalBatchV1",
                },
            )
        }
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    retried_window = next(
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.window_index == 1
    )

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.input_text_lengths == [1200, 1200, 1200]
    assert provider.output_recovery_markers == [None, None, "schema_validation"]
    assert retried_window.attempt_count == 2
    assert retried_window.effective_max_chars_per_chunk == 1200
    assert retried_window.previous_failure_category == "SCHEMA_VALIDATION_FAILED"


def test_worker_keeps_schema_failure_diagnostics_after_one_retry(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )
    schema_failure = ProviderResponseError(
        "LLM provider response failed schema validation",
        {
            "schema_error_kind": "missing",
            "schema_error_field_paths": ["events.0.summary"],
            "expected_output_schema": "EventProposalBatchV1",
        },
    )
    provider = _RetryingWindowProvider({2: schema_failure, 3: schema_failure})
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    failed_window = next(
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.window_index == 1
    )

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert failed_window.attempt_count == 2
    assert failed_window.effective_max_chars_per_chunk == 1200
    assert failed_window.previous_failure_category == "SCHEMA_VALIDATION_FAILED"
    assert failed_window.provider_error_diagnostics == {
        "schema_error_kind": "missing",
        "schema_error_field_paths": ["events.0.summary"],
        "expected_output_schema": "EventProposalBatchV1",
    }


def test_worker_executes_requested_modes_and_windows_in_fixed_order(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction", "entity_extraction", "claim_extraction"],
        real_llm_requested=True,
    )
    provider = _FakeProvider()
    agent_run_repository = _FakeAgentRunRepository()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.window_size == 3
    assert completed.stride == 2
    assert completed.concurrency == 1
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == [
        "event_extraction",
        "event_extraction",
        "entity_extraction",
        "entity_extraction",
        "claim_extraction",
        "claim_extraction",
    ]
    assert len(agent_run_repository.runs) == 6
    assert result is not None
    assert len(result.events) == 2
    assert len(result.entities) == 1
    assert len(result.claims) == 2
    assert all(item.agent_run_ids and item.evidence_refs for item in result.events)
    assert all(item.agent_run_ids and item.evidence_refs for item in result.entities)
    assert all(item.agent_run_ids and item.evidence_refs for item in result.claims)


def test_worker_preserves_successful_windows_and_resume_skips_them(tmp_path: Path) -> None:
    chunks = [_chunk(index) for index in range(5)]
    source_repository = _FakeSourceRepository(chunks)
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction", "entity_extraction"],
    )
    provider = _FakeProvider(fail_entity_once=True)
    agent_run_repository = _FakeAgentRunRepository()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        analysis_repository=analysis_repository,
        provider=provider,
    )

    first = worker.run_pending(run.analysis_run_id, real_llm_requested=True)
    calls_before_resume = list(provider.calls)
    successful_before_resume = {
        window.analysis_window_id: window.agent_run_id
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
    }
    successful_scopes_before_resume = {
        (window.mode, tuple(window.chunk_ids))
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
    }
    invocation_count_before_resume = len(provider.invocations)
    for deferred in analysis_repository.list_windows(run.analysis_run_id):
        if (
            deferred.parent_window_id is not None
            and deferred.next_eligible_retry_at is not None
        ):
            analysis_repository.save_window(
                deferred.model_copy(
                    update={
                        "next_eligible_retry_at": datetime.now(UTC) - timedelta(seconds=1)
                    }
                )
            )
    second = worker.run_pending(run.analysis_run_id, real_llm_requested=True)
    successful_after_resume = {
        window.analysis_window_id: window.agent_run_id
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
    }

    assert first.status == NarrativeAnalysisRunStatus.RUNNING
    assert second.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls.count("event_extraction") == calls_before_resume.count("event_extraction")
    assert all(
        (mode, tuple(chunk_ids)) not in successful_scopes_before_resume
        for mode, chunk_ids in provider.invocations[invocation_count_before_resume:]
    )
    assert successful_before_resume.items() <= successful_after_resume.items()
    assert all(agent_run_id is not None for agent_run_id in successful_before_resume.values())
    result = analysis_repository.get_result(run.analysis_run_id)
    assert result is not None
    assert len(result.events) == 2
    assert len(result.entities) == 1
    assert len(result.entities[0].evidence_refs) == 3


@pytest.mark.parametrize("empty", [False, True])
def test_worker_treats_knowledge_state_batches_as_successful_and_aggregates_states(
    tmp_path: Path, empty: bool
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["knowledge_state_extraction"],
        real_llm_requested=True,
    )
    provider = _KnowledgeStateWindowProvider(empty=empty)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["knowledge_state_extraction"]
    assert result is not None
    assert len(result.knowledge_states) == (0 if empty else 1)


def test_worker_flattens_multiple_knowledge_states_without_merging_statuses(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["knowledge_state_extraction"],
        real_llm_requested=True,
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=_KnowledgeStateWindowProvider(multiple=True),
    )

    worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert result is not None
    assert [item.proposal.epistemic_status for item in result.knowledge_states] == [
        "SUSPECTS",
        "BELIEVES",
    ]


def test_worker_merges_same_knowledge_state_across_windows_and_skips_success_on_resume(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["knowledge_state_extraction"],
        real_llm_requested=True,
    )
    provider = _KnowledgeStateWindowProvider()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    first = worker.run_pending(run.analysis_run_id)
    calls_before_resume = list(provider.calls)
    second = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert first.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert second.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == calls_before_resume
    assert result is not None
    assert len(result.knowledge_states) == 1
    assert len(result.knowledge_states[0].agent_run_ids) == 2
    assert len(result.knowledge_states[0].evidence_refs) == 2


@pytest.mark.parametrize("empty", [False, True])
def test_worker_treats_state_change_batches_as_successful_and_aggregates_changes(
    tmp_path: Path, empty: bool
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(empty=empty)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["state_change_extraction"]
    assert result is not None
    assert len(result.state_changes) == (0 if empty else 1)


def test_worker_merges_state_changes_across_windows_and_skips_success_on_resume(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    first = worker.run_pending(run.analysis_run_id)
    calls_before_resume = list(provider.calls)
    second = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert first.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert second.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == calls_before_resume
    assert result is not None
    assert len(result.state_changes) == 1
    assert len(result.state_changes[0].agent_run_ids) == 1
    assert len(result.state_changes[0].evidence_refs) == 1


def test_worker_recovers_a_state_change_schema_failure_once(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(5)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(
        failures={
            2: ProviderResponseError(
                "LLM provider response failed schema validation",
                {
                    "schema_error_kind": "missing",
                    "schema_error_field_paths": ["changes.0.target"],
                    "expected_output_schema": "StateChangeProposalBatchV1",
                },
            )
        }
    )
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    retried_window = next(
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.window_index == 1
    )

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["state_change_extraction"] * 3
    assert retried_window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
    assert retried_window.attempt_count == 2
    assert retried_window.previous_failure_category == "SCHEMA_VALIDATION_FAILED"


def test_worker_state_change_quantity_schema_recovery_preserves_all_changes(
    tmp_path: Path,
) -> None:
    source = _chunk(0).model_copy(
        update={
            "text": "阿葵把卷轴交给周砚，周砚又把卷轴交给沈策，沈策再交给陆衡；药瓶数量从六变为四。"
        }
    )
    source_repository = _FakeSourceRepository([source])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeQuantityRecoveryProvider()
    agent_run_repository = _FakeAgentRunRepository()
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == 2
    assert provider.output_recovery_markers == [None, "state_change_schema_recovery"]
    assert "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER" in provider.rule_codes
    assert "STATE_CHANGE_QUANTITY_MUST_BE_JSON_NUMBER" in provider.recovery_rule_codes
    failed_agent_runs = [
        agent_run
        for agent_run in agent_run_repository.runs.values()
        if agent_run.status == AgentRunStatus.FAILED
    ]
    assert failed_agent_runs
    diagnostics = failed_agent_runs[0].payload.get("provider_error_diagnostics")
    assert diagnostics is not None
    assert "schema_error_rule_codes" in diagnostics
    assert result is not None
    assert len(result.state_changes) == 4
    quantity = next(
        item.proposal for item in result.state_changes if item.proposal.attribute_path == "quantity"
    )
    assert quantity.old_value == 6
    assert quantity.new_value == 4
    assert all("raw" not in str(item) for item in diagnostics.values())


def test_worker_does_not_convert_source_only_state_change_rejection_to_success(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(invalid_evidence=True)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)
    failed_window = analysis_repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION
    assert provider.calls == ["state_change_extraction"] * 2
    assert result is None
    assert failed_window.status == NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION
    assert failed_window.failure_category == "EVIDENCE_REPAIR_EXHAUSTED"


def test_worker_rebinds_unique_verbatim_state_change_evidence_chunk(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(invalid_evidence=True)
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["state_change_extraction"]
    assert result is not None
    assert result.state_changes[0].proposal.evidence_refs[0].chunk_id == _chunk(0).chunk_id


def test_worker_repairs_non_verbatim_state_change_evidence_once(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(
        invalid_evidence_quote=True,
        repair_evidence_on_retry=True,
    )
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["state_change_extraction"] * 2
    assert provider.output_recovery_markers == [None, "evidence_validation"]


def test_worker_stops_after_one_non_verbatim_evidence_repair(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(invalid_evidence_quote=True)
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)
    window = analysis_repository.list_windows(run.analysis_run_id)[0]

    assert completed.status == NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION
    assert provider.calls == ["state_change_extraction"] * 2
    assert window.status == NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION
    assert window.failure_category == "EVIDENCE_REPAIR_EXHAUSTED"


def test_worker_normalizes_verbatim_state_change_evidence_before_offset_validation(
    tmp_path: Path,
) -> None:
    source_repository = _FakeSourceRepository([_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["state_change_extraction"],
        real_llm_requested=True,
    )
    provider = _StateChangeWindowProvider(mismatched_evidence_offsets=True)
    worker = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    )

    completed = worker.run_pending(run.analysis_run_id)
    result = analysis_repository.get_result(run.analysis_run_id)

    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert provider.calls == ["state_change_extraction"]
    assert result is not None
    evidence = result.state_changes[0].proposal.evidence_refs[0]
    assert evidence.quote_text == "synt"
    assert evidence.quote_start == 0
    assert evidence.quote_end == 4


def test_rockery_cross_window_event_wording_stays_separate_for_manual_review() -> None:
    quote = "假山直接崩塌下来。"

    def proposal(proposal_id: str, event_summary: str, chunk_id: str) -> StateChangeProposalV1:
        return StateChangeProposalV1.model_validate(
            {
                "schema_version": "1.2",
                "proposal_id": proposal_id,
                "event": {
                    "event_summary": event_summary,
                    "event_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "target": {
                    "mention_text": "假山",
                    "target_kind": "OBJECT",
                    "entity_proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "attribute_path": "physical.condition",
                "old_value": None,
                "new_value": "崩塌",
                "persistent": False,
                "reality_layer": "PRIMARY",
                "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                "new_value_evidence_indexes": [0],
                "persistence_evidence_indexes": [],
                "confidence": 0.9,
            }
        )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="rockery-run-1",
                proposal=proposal("rockery-proposal-1", "周元重拍假山", "rockery-chunk-1"),
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="rockery-run-2",
                proposal=proposal("rockery-proposal-2", "拳头重拍在假山上", "rockery-chunk-2"),
            ),
        ]
    )

    assert len(result.state_changes) == 2
    assert [item.proposal.event.event_summary for item in result.state_changes] == [
        "周元重拍假山",
        "拳头重拍在假山上",
    ]
    assert [item.agent_run_ids for item in result.state_changes] == [
        ["rockery-run-1"],
        ["rockery-run-2"],
    ]


def test_aggregate_state_changes_merges_only_exact_v12_semantics() -> None:
    base = StateChangeProposalV1.model_validate(
        {
            "schema_version": "1.2",
            "proposal_id": "state-change-1",
            "event": {
                "event_summary": "门关闭",
                "event_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "mention_text": "青铜门",
                "target_kind": "OBJECT",
                "entity_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": "accessibility",
            "old_value": None,
            "new_value": "关闭",
            "persistent": False,
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "青铜门关闭"}],
            "new_value_evidence_indexes": [0],
            "persistence_evidence_indexes": [],
            "confidence": 0.8,
        }
    )
    same = base.model_copy(
        update={
            "proposal_id": "state-change-2",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2", quote_text="青铜门关闭")],
        }
    )
    changed_value = base.model_copy(
        update={
            "proposal_id": "state-change-3",
            "new_value": "开启",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-3", quote_text="青铜门开启")],
        }
    )
    changed_path = base.model_copy(
        update={
            "proposal_id": "state-change-4",
            "attribute_path": "physical.condition",
            "new_value": "损坏",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-4", quote_text="门损坏")],
        }
    )
    changed_persistence = base.model_copy(
        update={
            "proposal_id": "state-change-5",
            "persistent": True,
            "persistence_evidence_indexes": [0],
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-5", quote_text="门永久关闭")],
        }
    )
    resolved = StateChangeProposalV1.model_validate(
        {
            **base.model_dump(mode="json"),
            "proposal_id": "state-change-6",
            "event": {
                "event_summary": "门关闭",
                "event_proposal_id": "event-proposal-1",
                "proposal_schema": "EventProposalV1",
                "resolution_status": "RESOLVED",
            },
            "target": {
                "mention_text": "青铜门",
                "target_kind": "OBJECT",
                "entity_proposal_id": "entity-proposal-1",
                "proposal_schema": "EntityProposalV1",
                "resolution_status": "RESOLVED",
            },
            "evidence_refs": [{"chunk_id": "chunk-6", "quote_text": "青铜门关闭"}],
        }
    )
    numeric_legacy_value = StateChangeProposalV1.model_validate(
        {
            "schema_version": "1.1",
            "proposal_id": "state-change-7",
            "event": {
                "event_summary": "库存更新",
                "event_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "mention_text": "仓库",
                "entity_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": "legacy_status",
            "old_value": None,
            "new_value": 1,
            "persistent": False,
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-7", "quote_text": "库存更新"}],
            "confidence": 0.8,
        }
    )
    string_legacy_value = StateChangeProposalV1.model_validate(
        {
            **numeric_legacy_value.model_dump(mode="json"),
            "proposal_id": "state-change-8",
            "new_value": "1",
            "evidence_refs": [{"chunk_id": "chunk-8", "quote_text": "库存更新"}],
        }
    )
    same_id_different_semantics = base.model_copy(
        update={
            "proposal_id": "state-change-1",
            "new_value": "半开",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-9", quote_text="青铜门半开")],
        }
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-1", proposal=base
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-2", proposal=same
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-3", proposal=changed_value
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-4", proposal=changed_path
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="run-5",
                proposal=changed_persistence,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-6", proposal=resolved
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="run-7",
                proposal=numeric_legacy_value,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="run-8",
                proposal=string_legacy_value,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction",
                agent_run_id="run-9",
                proposal=same_id_different_semantics,
            ),
        ]
    )

    assert len(result.state_changes) == 8
    assert result.state_changes[0].agent_run_ids == ["run-1", "run-2"]
    assert len(result.state_changes[0].evidence_refs) == 2
    assert [item.proposal.new_value for item in result.state_changes] == [
        "关闭",
        "开启",
        "损坏",
        "关闭",
        "关闭",
        1,
        "1",
        "半开",
    ]


def test_aggregate_state_changes_merges_exact_v13_appearance_candidates() -> None:
    base = StateChangeProposalV1.model_validate(
        {
            "schema_version": "1.3",
            "proposal_id": "state-change-v13-1",
            "event": {
                "event_summary": "换上灰衣",
                "event_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "mention_text": "周砚",
                "target_kind": "CHARACTER",
                "entity_proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": "appearance.clothing",
            "old_value": "湿外袍",
            "new_value": "灰衣",
            "persistent": False,
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-v13-1", "quote_text": "换上灰衣"}],
            "new_value_evidence_indexes": [0],
            "persistence_evidence_indexes": [],
            "confidence": 0.9,
        }
    )
    same = base.model_copy(
        update={
            "proposal_id": "state-change-v13-2",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-v13-2", quote_text="换上灰衣")],
        }
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-v13-1", proposal=base
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="state_change_extraction", agent_run_id="run-v13-2", proposal=same
            ),
        ]
    )

    assert len(result.state_changes) == 1
    assert result.state_changes[0].proposal.attribute_path == "appearance.clothing"
    assert result.state_changes[0].agent_run_ids == ["run-v13-1", "run-v13-2"]


def test_aggregate_narrative_analysis_merges_only_the_documented_exact_keys() -> None:
    event_a = EventProposalV1(
        proposal_id="event-a",
        event_type="handoff",
        summary="A hands over a token",
        participant_ids=[],
        actor_resolution_status="UNKNOWN",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="hands over")],
        confidence=0.8,
        reality_layer=RealityLayer.PRIMARY,
    )
    event_same = event_a.model_copy(update={"proposal_id": "event-same"})
    event_other_evidence = event_a.model_copy(
        update={
            "proposal_id": "event-other-evidence",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2", quote_text="hands over")],
        }
    )
    entity_a = EntityProposalV1(
        proposal_id="entity-a",
        entity_type="CREATURE",
        canonical_name="Synthetic creature",
        aliases=[],
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="creature")],
        confidence=0.8,
    )
    entity_same = entity_a.model_copy(
        update={
            "proposal_id": "entity-same",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2", quote_text="creature")],
        }
    )
    claim_a = ClaimProposalV1(
        proposal_id="claim-a",
        claim_type="FACTUAL_ASSERTION",
        claim_text="The gate is sealed.",
        temporal_scope="PRESENT",
        source_type="NARRATOR",
        verification_status="UNVERIFIED",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="gate is sealed")],
        confidence=0.8,
        reality_layer=RealityLayer.PRIMARY,
    )
    claim_same = claim_a.model_copy(update={"proposal_id": "claim-same"})
    claim_other_evidence = claim_a.model_copy(
        update={
            "proposal_id": "claim-other-evidence",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2", quote_text="gate is sealed")],
        }
    )
    claim_other_source_type = claim_a.model_copy(
        update={"proposal_id": "claim-other-source", "source_type": "CHARACTER"}
    )
    entity_other_type = entity_a.model_copy(
        update={"proposal_id": "entity-other-type", "entity_type": "OBJECT"}
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="event_extraction", agent_run_id="run-event-1", proposal=event_a
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="event_extraction", agent_run_id="run-event-2", proposal=event_same
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="event_extraction", agent_run_id="run-event-3", proposal=event_other_evidence
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="entity_extraction", agent_run_id="run-entity-1", proposal=entity_a
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="entity_extraction", agent_run_id="run-entity-2", proposal=entity_same
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="entity_extraction", agent_run_id="run-entity-3", proposal=entity_other_type
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="claim_extraction", agent_run_id="run-claim-1", proposal=claim_a
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="claim_extraction", agent_run_id="run-claim-2", proposal=claim_same
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="claim_extraction", agent_run_id="run-claim-3", proposal=claim_other_evidence
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="claim_extraction",
                agent_run_id="run-claim-4",
                proposal=claim_other_source_type,
            ),
        ]
    )

    assert len(result.events) == 2
    assert result.events[0].agent_run_ids == ["run-event-1", "run-event-2"]
    assert len(result.entities) == 2
    assert result.entities[0].agent_run_ids == ["run-entity-1", "run-entity-2"]
    assert len(result.entities[0].evidence_refs) == 2
    assert len(result.claims) == 3
    assert result.claims[0].agent_run_ids == ["run-claim-1", "run-claim-2"]


def test_aggregate_knowledge_states_merges_only_identical_resolution_aware_keys() -> None:
    base = KnowledgeStateProposalV1.model_validate(
        {
            "proposal_id": "knowledge-1",
            "subject": {
                "mention_text": "沈策",
                "entity_proposal_id": "entity-shence",
                "resolution_status": "RESOLVED",
            },
            "target": {
                "target_kind": "WORLD_FACT",
                "target_text": "出口存在",
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "epistemic_status": "BELIEVES",
            "epistemic_basis": "HEARD",
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-1"}],
            "confidence": 0.8,
        }
    )
    same = base.model_copy(
        update={"proposal_id": "knowledge-2", "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2")]}
    )
    unresolved = KnowledgeStateProposalV1.model_validate(
        base.model_dump(mode="json")
        | {
            "proposal_id": "knowledge-3",
            "subject": {
                "mention_text": "沈策",
                "entity_proposal_id": None,
                "resolution_status": "UNRESOLVED",
            },
        }
    )
    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-1", proposal=base
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-2", proposal=same
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-3", proposal=unresolved
            ),
        ]
    )

    assert len(result.knowledge_states) == 2
    assert result.knowledge_states[0].agent_run_ids == ["run-1", "run-2"]
    assert len(result.knowledge_states[0].evidence_refs) == 2


def test_aggregate_knowledge_states_never_merges_same_id_when_target_text_or_basis_differs() -> (
    None
):
    base = KnowledgeStateProposalV1.model_validate(
        {
            "proposal_id": "ksp-shared",
            "subject": {
                "mention_text": "甲",
                "entity_proposal_id": "entity-a",
                "resolution_status": "RESOLVED",
            },
            "target": {
                "target_kind": "WORLD_FACT",
                "target_text": "出口存在",
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "epistemic_status": "BELIEVES",
            "epistemic_basis": "HEARD",
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-1"}],
            "confidence": 0.8,
        }
    )
    changed_target = base.model_copy(
        update={
            "target": base.target.model_copy(update={"target_text": "出口不存在"}),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2")],
        }
    )
    changed_basis = base.model_copy(
        update={
            "epistemic_basis": "OBSERVED",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-3")],
        }
    )
    changed_anchor = base.model_copy(
        update={
            "valid_from": KnowledgeTemporalAnchorV1(
                anchor_text="门关闭之后",
                event_proposal_id=None,
                resolution_status="UNRESOLVED",
            ),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-4")],
        }
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-a", proposal=base
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-b", proposal=changed_target
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-c", proposal=changed_basis
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-d", proposal=changed_anchor
            ),
        ]
    )

    assert len(result.knowledge_states) == 4
    assert [item.agent_run_ids for item in result.knowledge_states] == [
        ["run-a"],
        ["run-b"],
        ["run-c"],
        ["run-d"],
    ]


def test_aggregate_knowledge_states_preserves_cross_window_target_kind_and_text_variants() -> None:
    base = KnowledgeStateProposalV1.model_validate(
        {
            "proposal_id": "knowledge-world-1",
            "subject": {
                "mention_text": "林舟",
                "entity_proposal_id": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "target_kind": "WORLD_FACT",
                "target_text": "守卫故意隐瞒了山路的位置",
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "epistemic_status": "SUSPECTS",
            "epistemic_basis": "INFERRED",
            "reality_layer": "PRIMARY",
            "evidence_refs": [{"chunk_id": "chunk-1"}],
            "confidence": 0.8,
        }
    )
    exact_repeat = base.model_copy(
        update={
            "proposal_id": "knowledge-world-2",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-2")],
        }
    )
    target_kind_variant = KnowledgeStateProposalV1.model_validate(
        base.model_dump(mode="json")
        | {
            "proposal_id": "knowledge-claim-1",
            "target": base.target.model_dump(mode="json") | {"target_kind": "CLAIM"},
            "epistemic_status": "HEARD",
            "epistemic_basis": "HEARD",
            "evidence_refs": [{"chunk_id": "chunk-3"}],
        }
    )
    core_target = base.model_copy(
        update={
            "proposal_id": "knowledge-core-1",
            "target": base.target.model_copy(update={"target_text": "山中有鬼"}),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-4")],
        }
    )
    target_text_variant = base.model_copy(
        update={
            "proposal_id": "knowledge-rumor-1",
            "target": base.target.model_copy(
                update={"target_text": "山中有鬼的传言"}
            ),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-5")],
        }
    )
    changed_status = base.model_copy(
        update={
            "proposal_id": "knowledge-status-1",
            "epistemic_status": "DISBELIEVES",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-6")],
        }
    )
    changed_basis = base.model_copy(
        update={
            "proposal_id": "knowledge-basis-1",
            "epistemic_basis": "HEARD",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-7")],
        }
    )
    changed_subject = base.model_copy(
        update={
            "proposal_id": "knowledge-subject-1",
            "subject": base.subject.model_copy(update={"mention_text": "苏岚"}),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-8")],
        }
    )
    changed_reality = base.model_copy(
        update={
            "proposal_id": "knowledge-reality-1",
            "reality_layer": "DREAM",
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-9")],
        }
    )
    changed_anchor = base.model_copy(
        update={
            "proposal_id": "knowledge-anchor-1",
            "valid_until": KnowledgeTemporalAnchorV1(
                anchor_text="离开小镇之后",
                event_proposal_id=None,
                resolution_status="UNRESOLVED",
            ),
            "evidence_refs": [EvidenceRefV1(chunk_id="chunk-10")],
        }
    )

    result = aggregate_narrative_analysis(
        [
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-1", proposal=base
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-2", proposal=exact_repeat
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction",
                agent_run_id="run-3",
                proposal=target_kind_variant,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction",
                agent_run_id="run-4",
                proposal=core_target,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction",
                agent_run_id="run-5",
                proposal=target_text_variant,
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-6", proposal=changed_status
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-7", proposal=changed_basis
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-8", proposal=changed_subject
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-9", proposal=changed_reality
            ),
            NarrativeAnalysisProposalSourceV1(
                mode="knowledge_state_extraction", agent_run_id="run-10", proposal=changed_anchor
            ),
        ]
    )

    assert len(result.knowledge_states) == 9
    assert result.knowledge_states[0].agent_run_ids == ["run-1", "run-2"]
    assert len(result.knowledge_states[0].evidence_refs) == 2
    assert {item.proposal.target.target_kind for item in result.knowledge_states} == {
        "CLAIM",
        "WORLD_FACT",
    }
    assert {item.proposal.target.target_text for item in result.knowledge_states} >= {
        "守卫故意隐瞒了山路的位置",
        "山中有鬼",
        "山中有鬼的传言",
    }


def test_schema_repair_exhaustion_is_explicit_and_never_enters_gate2(tmp_path: Path) -> None:
    """A minimum scope schema failure stops safely instead of producing a partial aggregate."""

    source_repository = _FakeSourceRepository([_long_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        max_split_depth=0,
        real_llm_requested=True,
    )
    schema_error = ProviderResponseError(
        "LLM provider response failed schema validation",
        {
            "schema_error_kind": "missing",
            "schema_error_field_paths": ["events.0.summary"],
            "schema_error_rule_codes": ["SCHEMA_CONTRACT_INVALID"],
            "expected_output_schema": "EventProposalBatchV1",
        },
    )
    provider = _RetryingWindowProvider({1: schema_error, 2: schema_error})
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    window = analysis_repository.list_windows(run.analysis_run_id)[0]
    assert completed.status == NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION
    assert window.status == NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION
    assert window.failure_category == "SCHEMA_REPAIR_EXHAUSTED"
    assert window.provider_request_count == 2
    assert analysis_repository.get_result(run.analysis_run_id) is None
    assert completed.review_gate2_result is None
    assert completed.review_gate2_route is None


def test_auditable_empty_event_scope_aggregates_without_an_invalid_placeholder(
    tmp_path: Path,
) -> None:
    """A source slice may safely contribute no Event without inventing one."""

    source_repository = _FakeSourceRepository([_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        real_llm_requested=True,
    )

    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=_EmptyEventProvider(),
    ).run_pending(run.analysis_run_id)

    result = analysis_repository.get_result(run.analysis_run_id)
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert result is not None
    assert result.events == []


def test_schema_repair_then_chunk_split_preserves_successful_siblings(tmp_path: Path) -> None:
    """The second schema failure narrows only its window and may still complete the root."""

    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        max_split_depth=1,
        real_llm_requested=True,
    )
    schema_error = ProviderResponseError(
        "LLM provider response failed schema validation",
        {"schema_error_kind": "missing", "schema_error_field_paths": ["events.0.summary"]},
    )
    provider = _RetryingWindowProvider({1: schema_error, 2: schema_error})
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    windows = analysis_repository.list_windows(run.analysis_run_id)
    parent = next(
        window for window in windows if window.status == NarrativeAnalysisWindowStatus.SPLIT
    )
    children = [
        window for window in windows if window.parent_window_id == parent.analysis_window_id
    ]
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert parent.provider_request_count == 2
    assert all(child.status == NarrativeAnalysisWindowStatus.SUCCEEDED for child in children)
    assert all(child.chunk_ids == child.owned_chunk_ids for child in children)
    assert len(provider.input_text_lengths) == 2 + len(children)


def test_schema_repair_single_chunk_uses_non_overlapping_auditable_slices(tmp_path: Path) -> None:
    source_repository = _FakeSourceRepository([_long_chunk(0)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        max_split_depth=1,
        real_llm_requested=True,
    )
    schema_error = ProviderResponseError(
        "LLM provider response failed schema validation",
        {"schema_error_kind": "missing", "schema_error_field_paths": ["events.0.summary"]},
    )
    provider = _RetryingWindowProvider({1: schema_error, 2: schema_error})
    completed = NarrativeAnalysisWorker(
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            narrative_window_min_slice_chars=100,
        ),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    slices = [
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.slice_chunk_id is not None
    ]
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert [(item.slice_start, item.slice_end) for item in slices] == [
        (0, 705),
        (705, 1410),
    ]
    assert all(item.status == NarrativeAnalysisWindowStatus.SUCCEEDED for item in slices)
    assert all(item.chunk_ids == ["chunk-0"] for item in slices)


def test_schema_repair_single_chunk_prefers_sentence_boundary_for_slices(tmp_path: Path) -> None:
    """Schema recovery preserves a complete sentence instead of cutting it in half."""

    text = ("甲" * 520) + "。" + ("乙" * 400)
    source_repository = _FakeSourceRepository([_chunk(0).model_copy(update={"text": text})])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        max_split_depth=1,
        real_llm_requested=True,
    )
    schema_error = ProviderResponseError(
        "LLM provider response failed schema validation",
        {"schema_error_kind": "missing", "schema_error_field_paths": ["events.0.summary"]},
    )
    provider = _RetryingWindowProvider({1: schema_error, 2: schema_error})

    NarrativeAnalysisWorker(
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            narrative_window_min_slice_chars=100,
        ),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    slices = [
        window
        for window in analysis_repository.list_windows(run.analysis_run_id)
        if window.slice_chunk_id is not None
    ]
    boundary = slices[0].slice_end
    assert boundary == 521
    assert text[boundary - 1] in "。！？!?\n"
    assert [(item.slice_start, item.slice_end) for item in slices] == [
        (0, boundary),
        (boundary, len(text)),
    ]


def test_length_split_child_gets_independent_schema_repair_budget(tmp_path: Path) -> None:
    """A child that used its length retry still receives its one Schema repair call."""

    source_repository = _FakeSourceRepository([_long_chunk(index) for index in range(3)])
    analysis_repository = _repository(tmp_path)
    run = create_narrative_analysis_run(
        source_repository=source_repository,
        analysis_repository=analysis_repository,
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        max_split_depth=1,
        real_llm_requested=True,
    )
    length_error = ProviderResponseError(
        "LLM provider response exceeded max output tokens before final content",
        {"finish_reason": "length"},
    )
    schema_error = ProviderResponseError(
        "LLM provider response failed schema validation",
        {
            "schema_error_kind": "missing",
            "schema_error_field_paths": ["events.0.summary"],
            "schema_error_rule_codes": ["SCHEMA_CONTRACT_INVALID"],
            "expected_output_schema": "EventProposalBatchV1",
        },
    )
    provider = _RetryingWindowProvider({1: length_error, 2: length_error, 3: schema_error})
    completed = NarrativeAnalysisWorker(
        settings=Settings(_env_file=None, enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=_FakeAgentRunRepository(),
        analysis_repository=analysis_repository,
        provider=provider,
    ).run_pending(run.analysis_run_id)

    windows = analysis_repository.list_windows(run.analysis_run_id)
    schema_child = next(
        window
        for window in windows
        if window.failure_category is None
        and window.previous_failure_category == "SCHEMA_VALIDATION_FAILED"
    )
    assert completed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert schema_child.provider_request_count == 3
    assert schema_child.schema_recovery_attempt_count == 1
    assert schema_child.schema_repair_attempts_used == 1
    assert schema_child.length_recovery_attempts_used == 1
    assert str(schema_child.recovery_phase) == "SCHEMA_REPAIR"
    assert "schema_validation" in provider.output_recovery_markers
    assert analysis_repository.get_result(run.analysis_run_id) is not None
