"""Regression coverage for durable, provider-free Gate 2 handoff recovery."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunStatus,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
    NarrativeGate2HandoffStatus,
)
from comic_agent.services.narrative_analysis_review_coordinator import (
    NarrativeGate2HandoffCoordinator,
)
from comic_agent.services.review_gate2_service import ReviewGate2Service


class _SourceRepository:
    def __init__(self) -> None:
        self.chunk = SourceChunkV1(
            chunk_id="chunk-1",
            project_id="project-1",
            document_id="document-1",
            chapter_id="chapter-1",
            order=0,
            text="safe test source",
            checksum="safe",
        )
        self._gate1 = SimpleNamespace(
            approved_chunk_bundle=SimpleNamespace(chunk_ids=[self.chunk.chunk_id])
        )

    def list_document_chunks(self, document_id: str) -> list[SourceChunkV1]:
        assert document_id == "document-1"
        return [self.chunk]

    def get_review_gate1(self, document_id: str):  # type: ignore[no-untyped-def]
        assert document_id == "document-1"
        return self._gate1


class _CountingReviewService(ReviewGate2Service):
    def __init__(self) -> None:
        self.calls = 0

    def review(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().review(*args, **kwargs)


class _FailingReviewService(ReviewGate2Service):
    def review(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("raw provider response must not be persisted")


def _seed(session_factory):  # type: ignore[no-untyped-def]
    session = session_factory()
    try:
        repository = NarrativeAnalysisRepository(session)
        run = NarrativeAnalysisRunV1(
            analysis_run_id="analysis-1",
            project_id="project-1",
            document_id="document-1",
            modes=["event_extraction"],
            status=NarrativeAnalysisRunStatus.SUCCEEDED,
            window_ids=["window-1"],
        )
        window = NarrativeAnalysisWindowV1(
            analysis_window_id="window-1",
            analysis_run_id=run.analysis_run_id,
            mode="event_extraction",
            window_index=0,
            chunk_ids=["chunk-1"],
            owned_chunk_ids=["chunk-1"],
            status=NarrativeAnalysisWindowStatus.SUCCEEDED,
            agent_run_id="agent-run-1",
        )
        repository.create_run(run, [window])
        repository.save_result(NarrativeAnalysisResultV1(analysis_run_id=run.analysis_run_id))
        return run.analysis_run_id
    finally:
        session.close()


def test_restart_resumes_only_gate2_after_persisted_narrative_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'gate2_handoff.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    run_id = _seed(session_factory)
    service = _CountingReviewService()

    session = session_factory()
    try:
        reviewed = NarrativeGate2HandoffCoordinator(
            source_repository=_SourceRepository(),
            analysis_repository=NarrativeAnalysisRepository(session),
            review_service=service,
        ).review_if_ready(run_id)
        aggregate = NarrativeAnalysisRepository(session).get_result(run_id)
        windows = NarrativeAnalysisRepository(session).list_windows(run_id)
    finally:
        session.close()

    assert reviewed.review_gate2_result is not None
    assert reviewed.review_gate2_route is not None
    assert reviewed.gate2_handoff is not None
    assert reviewed.gate2_handoff.status == NarrativeGate2HandoffStatus.COMPLETED
    assert aggregate is not None
    assert [window.status for window in windows] == [NarrativeAnalysisWindowStatus.SUCCEEDED]
    assert service.calls == 1


def test_two_sessions_claim_one_gate2_handoff_and_review_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'gate2_claim.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    run_id = _seed(session_factory)
    service = _CountingReviewService()

    def recover() -> None:
        session = session_factory()
        try:
            NarrativeGate2HandoffCoordinator(
                source_repository=_SourceRepository(),
                analysis_repository=NarrativeAnalysisRepository(session),
                review_service=service,
            ).review_if_ready(run_id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: recover(), range(2)))

    session = session_factory()
    try:
        run = NarrativeAnalysisRepository(session).get_run(run_id)
    finally:
        session.close()
    assert run is not None
    assert run.review_gate2_result is not None
    assert run.review_gate2_route is not None
    assert run.gate2_handoff is not None
    assert run.gate2_handoff.status == NarrativeGate2HandoffStatus.COMPLETED
    assert service.calls == 1


def test_gate2_handoff_failure_is_sanitized_and_resume_only_retries_gate2(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'gate2_failure.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    run_id = _seed(session_factory)

    session = session_factory()
    try:
        failed = NarrativeGate2HandoffCoordinator(
            source_repository=_SourceRepository(),
            analysis_repository=NarrativeAnalysisRepository(session),
            review_service=_FailingReviewService(),
        ).review_if_ready(run_id)
        aggregate = NarrativeAnalysisRepository(session).get_result(run_id)
    finally:
        session.close()
    assert failed.review_gate2_result is None
    assert failed.gate2_handoff is not None
    assert failed.gate2_handoff.status == NarrativeGate2HandoffStatus.FAILED
    assert failed.gate2_handoff.safe_issue_codes == ["GATE2_HANDOFF_FAILED"]
    assert "raw provider" not in failed.model_dump_json()
    assert aggregate is not None

    session = session_factory()
    try:
        resumed = NarrativeGate2HandoffCoordinator(
            source_repository=_SourceRepository(),
            analysis_repository=NarrativeAnalysisRepository(session),
            review_service=_CountingReviewService(),
        ).review_if_ready(run_id)
    finally:
        session.close()
    assert resumed.review_gate2_result is not None
    assert resumed.gate2_handoff is not None
    assert resumed.gate2_handoff.status == NarrativeGate2HandoffStatus.COMPLETED
