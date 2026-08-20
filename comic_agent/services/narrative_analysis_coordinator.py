"""Deterministic authorization and chapter selection for Narrative Analyst runs."""

from typing import Any

from comic_agent.config import Settings
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.review import SourceReviewDecision
from comic_agent.schemas.workflow import NarrativeAnalysisRunV1
from comic_agent.services.narrative_analysis import create_narrative_analysis_run

DEFAULT_NARRATIVE_ANALYST_MODES = [
    "entity_extraction",
    "event_extraction",
    "claim_extraction",
    "knowledge_state_extraction",
    "state_change_extraction",
    "relationship_signal_extraction",
]


class NarrativeAnalysisCoordinator:
    """Authorize only Gate 1-approved chapter chunks for analysis."""

    def __init__(
        self,
        *,
        source_repository: SourceRepository,
        analysis_repository: NarrativeAnalysisRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.source_repository = source_repository
        self.analysis_repository = analysis_repository
        self.settings = settings or Settings()

    def chapter_selection(self, *, project_id: str, document_id: str) -> dict[str, Any]:
        document = self.source_repository.get_document(document_id)
        if document is None or document.project_id != project_id:
            raise ValueError("document not found for project")
        gate1 = self.source_repository.get_review_gate1(document_id)
        chapters = self.source_repository.list_document_chapters(document_id)
        chunks = self.source_repository.list_document_chunks(document_id)
        approved_ids = (
            set(gate1.approved_chunk_bundle.chunk_ids)
            if gate1 and gate1.approved_chunk_bundle
            else set()
        )
        chapter_payload = []
        for chapter in chapters:
            chapter_chunks = [chunk for chunk in chunks if chunk.chapter_id == chapter.chapter_id]
            available = [chunk for chunk in chapter_chunks if chunk.chunk_id in approved_ids]
            chapter_payload.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "order": chapter.order,
                    "title": chapter.title,
                    "chunk_count": len(chapter_chunks),
                    "available_chunk_count": len(available),
                    "available": bool(available) and len(available) == len(chapter_chunks),
                }
            )
        eligible = bool(
            gate1
            and gate1.decision == SourceReviewDecision.APPROVED
            and gate1.approved_chunk_bundle is not None
            and approved_ids == {chunk.chunk_id for chunk in chunks}
        )
        return {
            "document_id": document.document_id,
            "revision": document.revision,
            "eligible": eligible,
            "gate1": gate1.model_dump(mode="json") if gate1 is not None else None,
            "chapters": chapter_payload,
            "default_modes": list(DEFAULT_NARRATIVE_ANALYST_MODES),
        }

    def create_run(
        self,
        *,
        project_id: str,
        document_id: str,
        chapter_ids: list[str] | None,
        modes: list[str],
        real_llm_requested: bool,
        document_revision: int | None = None,
    ) -> NarrativeAnalysisRunV1:
        if self.analysis_repository is None:
            raise ValueError("analysis repository is required to create a run")
        document = self.source_repository.get_document(document_id)
        if document is None or document.project_id != project_id:
            raise ValueError("document not found for project")
        if document_revision is not None and document.revision != document_revision:
            raise ValueError("document revision does not match")
        gate1 = self.source_repository.get_review_gate1(document_id)
        if (
            gate1 is None
            or gate1.decision != SourceReviewDecision.APPROVED
            or gate1.approved_chunk_bundle is None
        ):
            raise ValueError("document is not Gate 1 approved")
        chapters = self.source_repository.list_document_chapters(document_id)
        chapter_map = {chapter.chapter_id: chapter for chapter in chapters}
        if chapter_ids is None:
            selected_chapter_ids = [chapter.chapter_id for chapter in chapters]
        else:
            selected_chapter_ids = list(chapter_ids)
        if not selected_chapter_ids:
            raise ValueError("chapter_ids must select at least one chapter")
        if len(set(selected_chapter_ids)) != len(selected_chapter_ids):
            raise ValueError("chapter_ids must be distinct")
        if any(chapter_id not in chapter_map for chapter_id in selected_chapter_ids):
            raise ValueError("chapter selection contains an unknown chapter")
        chunks = self.source_repository.list_document_chunks(document_id)
        selected_chunks = [
            chunk for chunk in chunks if chunk.chapter_id in set(selected_chapter_ids)
        ]
        approved_ids = set(gate1.approved_chunk_bundle.chunk_ids)
        if not selected_chunks or any(
            chunk.chunk_id not in approved_ids for chunk in selected_chunks
        ):
            raise ValueError("chapter selection is outside the approved Gate 1 bundle")
        if not modes:
            raise ValueError("at least one NarrativeAnalyst mode is required")
        return create_narrative_analysis_run(
            source_repository=self.source_repository,
            analysis_repository=self.analysis_repository,
            project_id=project_id,
            document_id=document_id,
            modes=modes,
            real_llm_requested=real_llm_requested,
            selected_chunks=selected_chunks,
            batch_max_chunks=self.settings.narrative_batch_max_chunks,
            output_token_budget=self.settings.llm_max_output_tokens,
            time_budget_seconds=self.settings.narrative_window_time_budget_seconds,
            max_call_attempts=self.settings.narrative_window_max_call_attempts,
            max_split_depth=self.settings.narrative_window_max_split_depth,
        )
