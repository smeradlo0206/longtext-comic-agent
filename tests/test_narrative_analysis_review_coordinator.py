from types import SimpleNamespace

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    AggregatedEventProposalV1,
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunStatus,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.narrative_analysis_review_coordinator import (
    NarrativeAnalysisReviewCoordinator,
)
from comic_agent.services.review_gate2_service import ReviewGate2Service


class _SourceRepository:
    def __init__(self, chunks: list[SourceChunkV1], approved_chunk_ids: list[str]) -> None:
        self._chunks = chunks
        self._gate1 = SimpleNamespace(
            approved_chunk_bundle=SimpleNamespace(chunk_ids=approved_chunk_ids)
        )

    def list_document_chunks(self, document_id: str) -> list[SourceChunkV1]:
        assert document_id == "document-1"
        return self._chunks

    def get_review_gate1(self, document_id: str):
        assert document_id == "document-1"
        return self._gate1


class _AnalysisRepository:
    def __init__(
        self,
        run: NarrativeAnalysisRunV1,
        result: NarrativeAnalysisResultV1,
        windows: list[NarrativeAnalysisWindowV1],
    ) -> None:
        self.run = run
        self.result = result
        self.windows = windows
        self.saves = 0

    def get_run(self, analysis_run_id: str):
        return self.run if analysis_run_id == self.run.analysis_run_id else None

    def get_result(self, analysis_run_id: str):
        return self.result if analysis_run_id == self.run.analysis_run_id else None

    def list_windows(self, analysis_run_id: str):
        assert analysis_run_id == self.run.analysis_run_id
        return self.windows

    def save_review_gate2_artifacts(self, *, analysis_run_id: str, result, route):
        assert analysis_run_id == self.run.analysis_run_id
        self.saves += 1
        self.run = self.run.model_copy(
            update={
                "schema_version": "1.1",
                "review_gate2_result": result,
                "review_gate2_route": route,
            }
        )
        return self.run


class _CountingReviewService(ReviewGate2Service):
    def __init__(self) -> None:
        self.calls = 0

    def review(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().review(*args, **kwargs)


def _chunk() -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text="A verified event happens.",
        checksum="safe",
    )


def _run(status: NarrativeAnalysisRunStatus = NarrativeAnalysisRunStatus.SUCCEEDED):
    return NarrativeAnalysisRunV1(
        analysis_run_id="analysis-1",
        project_id="project-1",
        document_id="document-1",
        modes=["event_extraction"],
        status=status,
    )


def _window() -> NarrativeAnalysisWindowV1:
    return NarrativeAnalysisWindowV1(
        analysis_window_id="window-1",
        analysis_run_id="analysis-1",
        mode="event_extraction",
        window_index=0,
        chunk_ids=["chunk-1"],
        owned_chunk_ids=["chunk-1"],
        status=NarrativeAnalysisWindowStatus.SUCCEEDED,
        agent_run_id="agent-run-1",
    )


def _failed_window(
    status: NarrativeAnalysisWindowStatus = NarrativeAnalysisWindowStatus.EXHAUSTED,
) -> NarrativeAnalysisWindowV1:
    return NarrativeAnalysisWindowV1(
        analysis_window_id="window-failed-1",
        analysis_run_id="analysis-1",
        mode="event_extraction",
        window_index=1,
        chunk_ids=["chunk-1"],
        owned_chunk_ids=["chunk-1"],
        status=status,
        failure_category="PROVIDER_TIMEOUT",
        recommended_action="Wait for the configured retry window or request human action.",
    )


def test_completed_analysis_automatically_persists_one_idempotent_approved_gate2_route() -> None:
    chunk = _chunk()
    repository = _AnalysisRepository(
        _run(), NarrativeAnalysisResultV1(analysis_run_id="analysis-1"), [_window()]
    )
    service = _CountingReviewService()
    coordinator = NarrativeAnalysisReviewCoordinator(
        source_repository=_SourceRepository([chunk], [chunk.chunk_id]),
        analysis_repository=repository,  # type: ignore[arg-type]
        review_service=service,
    )

    first = coordinator.review_if_ready("analysis-1")
    second = coordinator.review_if_ready("analysis-1")

    assert first.review_gate2_route is not None
    assert first.review_gate2_route.decision == "APPROVED"
    assert first.review_gate2_route.approved_proposal_bundle is not None
    assert first.review_gate2_route.approved_proposal_bundle.approved_proposals == []
    assert second.review_gate2_result is not None
    assert second.review_gate2_result.review_run_id == first.review_gate2_result.review_run_id
    assert service.calls == 1
    assert repository.saves == 1


def test_partial_analysis_persists_execution_bundle_and_gate2_audit() -> None:
    chunk = _chunk()
    repository = _AnalysisRepository(
        _run(NarrativeAnalysisRunStatus.PARTIAL_FAILED),
        NarrativeAnalysisResultV1(analysis_run_id="analysis-1"),
        [_window(), _failed_window()],
    )
    service = _CountingReviewService()

    reviewed = NarrativeAnalysisReviewCoordinator(
        source_repository=_SourceRepository([chunk], [chunk.chunk_id]),
        analysis_repository=repository,  # type: ignore[arg-type]
        review_service=service,
    ).review_if_ready("analysis-1")

    assert reviewed.review_gate2_result is not None
    assert reviewed.review_gate2_route is not None
    assert reviewed.review_gate2_route.decision == "NEEDS_HUMAN_REVIEW"
    execution = reviewed.review_gate2_route.narrative_execution_bundle
    assert execution is not None
    assert execution.status == "PARTIAL_FAILED"
    assert [item.analysis_window_id for item in execution.failed_windows] == ["window-failed-1"]
    assert any(issue.code == "NARRATIVE_EXECUTION_INCOMPLETE" for issue in execution.issues)
    assert service.calls == 1


def test_needs_human_action_analysis_persists_execution_bundle_and_gate2_audit() -> None:
    chunk = _chunk()
    repository = _AnalysisRepository(
        _run(NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION),
        NarrativeAnalysisResultV1(analysis_run_id="analysis-1"),
        [
            _window(),
            _failed_window(NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION),
        ],
    )

    reviewed = NarrativeAnalysisReviewCoordinator(
        source_repository=_SourceRepository([chunk], [chunk.chunk_id]),
        analysis_repository=repository,  # type: ignore[arg-type]
    ).review_if_ready("analysis-1")

    assert reviewed.review_gate2_route is not None
    execution = reviewed.review_gate2_route.narrative_execution_bundle
    assert execution is not None
    assert execution.status == "NEEDS_HUMAN_ACTION"
    assert execution.failed_windows[0].status == "NEEDS_HUMAN_ACTION"


def test_rejected_evidence_is_persisted_as_a_safe_route_diagnostic() -> None:
    chunk = _chunk()
    invalid_event = EventProposalV1(
        proposal_id="event-1",
        event_type="DISCOVERY",
        summary="A verified event happens.",
        evidence_refs=[EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="not in source")],
        confidence=0.9,
        reality_layer="PRIMARY",
    )
    aggregate = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=invalid_event,
                agent_run_ids=["agent-run-1"],
                evidence_refs=invalid_event.evidence_refs,
            )
        ],
    )
    repository = _AnalysisRepository(_run(), aggregate, [_window()])

    reviewed = NarrativeAnalysisReviewCoordinator(
        source_repository=_SourceRepository([chunk], [chunk.chunk_id]),
        analysis_repository=repository,  # type: ignore[arg-type]
    ).review_if_ready("analysis-1")

    assert reviewed.status == NarrativeAnalysisRunStatus.SUCCEEDED
    assert reviewed.review_gate2_route is not None
    assert reviewed.review_gate2_route.decision == "REJECTED"
    assert reviewed.review_gate2_route.approved_proposal_bundle is None
    assert reviewed.review_gate2_route.narrative_execution_bundle is not None
    assert reviewed.review_gate2_route.narrative_execution_bundle.candidates == []
    assert [
        item.proposal_id
        for item in reviewed.review_gate2_route.narrative_execution_bundle.excluded_items
    ] == ["event-1"]
    assert reviewed.review_gate2_route.narrative_execution_bundle.issues
    assert reviewed.review_gate2_route.recovery_diagnostics[0].issue_codes == [
        "EVIDENCE_QUOTE_NOT_FOUND"
    ]


def test_repeated_evidence_issues_produce_one_route_diagnostic_code() -> None:
    chunk = _chunk()
    invalid_event = EventProposalV1(
        proposal_id="event-1",
        event_type="DISCOVERY",
        summary="A verified event happens.",
        evidence_refs=[
            EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="first missing quote"),
            EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="second missing quote"),
        ],
        confidence=0.9,
        reality_layer="PRIMARY",
    )
    aggregate = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=invalid_event,
                agent_run_ids=["agent-run-1"],
                evidence_refs=invalid_event.evidence_refs,
            )
        ],
    )
    repository = _AnalysisRepository(_run(), aggregate, [_window()])

    reviewed = NarrativeAnalysisReviewCoordinator(
        source_repository=_SourceRepository([chunk], [chunk.chunk_id]),
        analysis_repository=repository,  # type: ignore[arg-type]
    ).review_if_ready("analysis-1")

    assert reviewed.review_gate2_route is not None
    assert reviewed.review_gate2_route.decision == "REJECTED"
    assert reviewed.review_gate2_route.recovery_diagnostics[0].issue_codes == [
        "EVIDENCE_QUOTE_NOT_FOUND"
    ]
