"""Repository for source import and query operations."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from comic_agent.database.models import (
    AgentRunModel,
    EventProposalModel,
    ProjectModel,
    SourceChapterModel,
    SourceChunkModel,
    SourceDocumentModel,
    TimelineAnalysisProposalModel,
)
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.review import ReviewGate1ResultV1, SourceReviewDecision
from comic_agent.schemas.source import (
    ProjectSpecV1,
    SourceChapterV1,
    SourceChunkV1,
    SourceDocumentV1,
)
from comic_agent.schemas.workflow import AgentRunV1
from comic_agent.schemas.timeline import TimelineAnalysisProposalV1
from comic_agent.services.document_parser import ParsedDocument


@dataclass(frozen=True)
class ImportResult:
    """Result of an idempotent document import."""

    status: str
    document: SourceDocumentV1
    chapters: list[SourceChapterV1]
    chunks: list[SourceChunkV1]
    gate1_result: ReviewGate1ResultV1 | None = None


_GATE1_PAYLOAD_KEY = "__review_gate1__"


class SourceRepository:
    """Data access layer for project and source records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_project(self, project: ProjectSpecV1) -> ProjectSpecV1:
        """Create or update a project idempotently."""

        existing = self._session.get(ProjectModel, project.id)
        payload = project.model_dump(mode="json")
        if existing is None:
            self._session.add(
                ProjectModel(
                    id=project.id,
                    name=project.name,
                    project_type=str(project.project_type),
                    fidelity_mode=str(project.fidelity_mode),
                    payload=payload,
                )
            )
        else:
            existing.name = project.name
            existing.project_type = str(project.project_type)
            existing.fidelity_mode = str(project.fidelity_mode)
            existing.payload = payload
        self._session.commit()
        return project

    def get_project(self, project_id: str) -> ProjectSpecV1 | None:
        """Return a project by id."""

        row = self._session.get(ProjectModel, project_id)
        if row is None:
            return None
        return ProjectSpecV1.model_validate(row.payload)

    def import_parsed_document(self, parsed: ParsedDocument) -> ImportResult:
        """Persist parsed source data without creating duplicates."""

        existing = self._session.scalar(
            select(SourceDocumentModel).where(
                SourceDocumentModel.project_id == parsed.document.project_id,
                SourceDocumentModel.checksum == parsed.document.checksum,
            )
        )
        if existing is not None:
            document = self._document_from_payload(existing.payload)
            return ImportResult(
                status="existing",
                document=document,
                chapters=self.list_chapters(document.project_id),
                chunks=self.list_document_chunks(document.document_id),
                gate1_result=self._review_from_payload(existing.payload),
            )

        self._session.add(
            SourceDocumentModel(
                document_id=parsed.document.document_id,
                project_id=parsed.document.project_id,
                filename=parsed.document.filename,
                mime_type=parsed.document.mime_type,
                checksum=parsed.document.checksum,
                storage_uri=parsed.document.storage_uri,
                imported_at=parsed.document.imported_at,
                revision=parsed.document.revision,
                payload=parsed.document.model_dump(mode="json"),
            )
        )
        for chapter in parsed.chapters:
            self._session.add(
                SourceChapterModel(
                    chapter_id=chapter.chapter_id,
                    document_id=chapter.document_id,
                    project_id=chapter.project_id,
                    title=chapter.title,
                    order=chapter.order,
                    start_chunk_order=chapter.start_chunk_order,
                    end_chunk_order=chapter.end_chunk_order,
                    payload=chapter.model_dump(mode="json"),
                )
            )
        for chunk in parsed.chunks:
            self._session.add(
                SourceChunkModel(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    chapter_id=chunk.chapter_id,
                    project_id=chunk.project_id,
                    order=chunk.order,
                    text=chunk.text,
                    source_page=chunk.source_page,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    checksum=chunk.checksum,
                    payload=chunk.model_dump(mode="json"),
                )
            )
        self._session.commit()
        return ImportResult(
            status="created",
            document=parsed.document,
            chapters=parsed.chapters,
            chunks=parsed.chunks,
        )

    def import_reviewed_document(
        self,
        parsed: ParsedDocument,
        gate1_result: ReviewGate1ResultV1,
    ) -> ImportResult:
        """Persist source records only after an APPROVED Gate 1 result."""

        if gate1_result.decision != SourceReviewDecision.APPROVED:
            raise ValueError("only APPROVED Gate 1 results may be persisted")
        if gate1_result.approved_chunk_bundle is None:
            raise ValueError("APPROVED Gate 1 result requires an approved chunk bundle")

        existing = self._session.scalar(
            select(SourceDocumentModel).where(
                SourceDocumentModel.project_id == parsed.document.project_id,
                SourceDocumentModel.checksum == parsed.document.checksum,
            )
        )
        if existing is not None:
            existing.payload = {
                **existing.payload,
                _GATE1_PAYLOAD_KEY: gate1_result.model_dump(mode="json"),
            }
            self._session.commit()
            document = self._document_from_payload(existing.payload)
            return ImportResult(
                status="existing",
                document=document,
                chapters=self.list_document_chapters(document.document_id),
                chunks=self.list_document_chunks(document.document_id),
                gate1_result=gate1_result,
            )

        document_payload = {
            **parsed.document.model_dump(mode="json"),
            _GATE1_PAYLOAD_KEY: gate1_result.model_dump(mode="json"),
        }
        self._session.add(
            SourceDocumentModel(
                document_id=parsed.document.document_id,
                project_id=parsed.document.project_id,
                filename=parsed.document.filename,
                mime_type=parsed.document.mime_type,
                checksum=parsed.document.checksum,
                storage_uri=parsed.document.storage_uri,
                imported_at=parsed.document.imported_at,
                revision=parsed.document.revision,
                payload=document_payload,
            )
        )
        for chapter in parsed.chapters:
            self._session.add(
                SourceChapterModel(
                    chapter_id=chapter.chapter_id,
                    document_id=chapter.document_id,
                    project_id=chapter.project_id,
                    title=chapter.title,
                    order=chapter.order,
                    start_chunk_order=chapter.start_chunk_order,
                    end_chunk_order=chapter.end_chunk_order,
                    payload=chapter.model_dump(mode="json"),
                )
            )
        for chunk in parsed.chunks:
            self._session.add(
                SourceChunkModel(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    chapter_id=chunk.chapter_id,
                    project_id=chunk.project_id,
                    order=chunk.order,
                    text=chunk.text,
                    source_page=chunk.source_page,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    checksum=chunk.checksum,
                    payload=chunk.model_dump(mode="json"),
                )
            )
        self._session.commit()
        return ImportResult(
            status="created",
            document=parsed.document,
            chapters=parsed.chapters,
            chunks=parsed.chunks,
            gate1_result=gate1_result,
        )

    def get_document(self, document_id: str) -> SourceDocumentV1 | None:
        """Return one source document without exposing review metadata."""

        row = self._session.get(SourceDocumentModel, document_id)
        return self._document_from_payload(row.payload) if row is not None else None

    def get_review_gate1(self, document_id: str) -> ReviewGate1ResultV1 | None:
        """Return the sanitized Gate 1 artifact for an approved document."""

        row = self._session.get(SourceDocumentModel, document_id)
        return self._review_from_payload(row.payload) if row is not None else None

    def list_chapters(self, project_id: str) -> list[SourceChapterV1]:
        """Return chapters for a project ordered by source order."""

        rows = self._session.scalars(
            select(SourceChapterModel)
            .where(SourceChapterModel.project_id == project_id)
            .order_by(SourceChapterModel.order)
        ).all()
        return [SourceChapterV1.model_validate(row.payload) for row in rows]

    def list_documents(self, project_id: str) -> list[SourceDocumentV1]:
        """Return imported documents for the normal document-selection flow."""

        rows = self._session.scalars(
            select(SourceDocumentModel)
            .where(SourceDocumentModel.project_id == project_id)
            .order_by(SourceDocumentModel.imported_at, SourceDocumentModel.document_id)
        ).all()
        return [self._document_from_payload(row.payload) for row in rows]

    def list_document_chapters(self, document_id: str) -> list[SourceChapterV1]:
        """Return chapters for one document in source order."""

        rows = self._session.scalars(
            select(SourceChapterModel)
            .where(SourceChapterModel.document_id == document_id)
            .order_by(SourceChapterModel.order)
        ).all()
        return [SourceChapterV1.model_validate(row.payload) for row in rows]

    def list_document_chunks(self, document_id: str) -> list[SourceChunkV1]:
        """Return chunks for a document ordered by source order."""

        rows = self._session.scalars(
            select(SourceChunkModel)
            .where(SourceChunkModel.document_id == document_id)
            .order_by(SourceChunkModel.order)
        ).all()
        return [SourceChunkV1.model_validate(row.payload) for row in rows]

    def list_chunks_for_chapter(self, chapter_id: str) -> list[SourceChunkV1]:
        """Return chunks for a chapter ordered by source order."""

        rows = self._session.scalars(
            select(SourceChunkModel)
            .where(SourceChunkModel.chapter_id == chapter_id)
            .order_by(SourceChunkModel.order)
        ).all()
        return [SourceChunkV1.model_validate(row.payload) for row in rows]

    def list_project_chunks(self, project_id: str) -> list[SourceChunkV1]:
        """Return chunks for a project ordered by source order."""

        rows = self._session.scalars(
            select(SourceChunkModel)
            .where(SourceChunkModel.project_id == project_id)
            .order_by(SourceChunkModel.order, SourceChunkModel.chunk_id)
        ).all()
        return [SourceChunkV1.model_validate(row.payload) for row in rows]

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        """Return one source chunk by id."""

        row = self._session.get(SourceChunkModel, chunk_id)
        if row is None:
            return None
        return SourceChunkV1.model_validate(row.payload)

    def save_event_proposal(
        self,
        proposal: EventProposalV1,
        source_chunk: SourceChunkV1,
        agent_id: str,
    ) -> EventProposalV1:
        """Persist one candidate proposal idempotently for a chunk and agent."""

        existing = self._session.scalar(
            select(EventProposalModel).where(
                EventProposalModel.source_chunk_id == source_chunk.chunk_id,
                EventProposalModel.agent_id == agent_id,
            )
        )
        if existing is not None:
            return EventProposalV1.model_validate(existing.payload)

        self._session.add(
            EventProposalModel(
                proposal_id=proposal.proposal_id,
                project_id=source_chunk.project_id,
                source_chunk_id=source_chunk.chunk_id,
                agent_id=agent_id,
                status="CANDIDATE",
                payload=proposal.model_dump(mode="json"),
            )
        )
        self._session.commit()
        return proposal

    def get_event_proposal(self, proposal_id: str) -> EventProposalV1 | None:
        """Return one stored candidate proposal."""

        row = self._session.get(EventProposalModel, proposal_id)
        if row is None:
            return None
        return EventProposalV1.model_validate(row.payload)

    def list_event_proposals_for_chunk(self, chunk_id: str) -> list[EventProposalV1]:
        """Return candidate proposals for one source chunk."""

        rows = self._session.scalars(
            select(EventProposalModel)
            .where(EventProposalModel.source_chunk_id == chunk_id)
            .order_by(EventProposalModel.created_at)
        ).all()
        return [EventProposalV1.model_validate(row.payload) for row in rows]

    def save_timeline_analysis(
        self,
        proposal: TimelineAnalysisProposalV1,
        input_hash: str,
    ) -> TimelineAnalysisProposalV1:
        """Persist a project-scoped timeline candidate idempotently by input hash."""

        existing = self._session.scalar(
            select(TimelineAnalysisProposalModel).where(
                TimelineAnalysisProposalModel.project_id == proposal.project_id,
                TimelineAnalysisProposalModel.input_hash == input_hash,
            )
        )
        if existing is not None:
            return TimelineAnalysisProposalV1.model_validate(existing.payload)
        self._session.add(
            TimelineAnalysisProposalModel(
                proposal_id=proposal.proposal_id,
                project_id=proposal.project_id,
                input_hash=input_hash,
                status=str(proposal.status),
                payload=proposal.model_dump(mode="json"),
            )
        )
        self._session.commit()
        return proposal

    def get_timeline_analysis_by_input_hash(
        self,
        project_id: str,
        input_hash: str,
    ) -> TimelineAnalysisProposalV1 | None:
        """Return an idempotently cached analysis before another agent call is made."""

        row = self._session.scalar(
            select(TimelineAnalysisProposalModel).where(
                TimelineAnalysisProposalModel.project_id == project_id,
                TimelineAnalysisProposalModel.input_hash == input_hash,
            )
        )
        return TimelineAnalysisProposalV1.model_validate(row.payload) if row else None

    def get_timeline_analysis(
        self,
        project_id: str,
        proposal_id: str,
    ) -> TimelineAnalysisProposalV1 | None:
        """Return one project-owned timeline candidate."""

        row = self._session.get(TimelineAnalysisProposalModel, proposal_id)
        if row is None or row.project_id != project_id:
            return None
        return TimelineAnalysisProposalV1.model_validate(row.payload)

    def list_timeline_analyses(self, project_id: str) -> list[TimelineAnalysisProposalV1]:
        """List timeline candidates in creation order for one project."""

        rows = self._session.scalars(
            select(TimelineAnalysisProposalModel)
            .where(TimelineAnalysisProposalModel.project_id == project_id)
            .order_by(TimelineAnalysisProposalModel.created_at)
        ).all()
        return [TimelineAnalysisProposalV1.model_validate(row.payload) for row in rows]

    def save_agent_run(self, agent_run: AgentRunV1) -> AgentRunV1:
        """Persist one immutable agent execution trace."""

        self._session.add(
            AgentRunModel(
                agent_run_id=agent_run.agent_run_id,
                project_id=agent_run.project_id,
                source_chunk_id=agent_run.source_chunk_id,
                output_proposal_id=agent_run.output_proposal_id,
                workflow_run_id=agent_run.workflow_run_id,
                agent_id=agent_run.agent_id,
                status=agent_run.status,
                payload=agent_run.model_dump(mode="json"),
                created_at=agent_run.created_at,
            )
        )
        self._session.commit()
        return agent_run

    def get_agent_run(self, agent_run_id: str) -> AgentRunV1 | None:
        """Return one stored agent execution trace."""

        row = self._session.get(AgentRunModel, agent_run_id)
        if row is None:
            return None
        return AgentRunV1.model_validate(row.payload)

    def list_agent_runs_for_chunk(self, chunk_id: str) -> list[AgentRunV1]:
        """Return agent execution traces for one source chunk."""

        rows = self._session.scalars(
            select(AgentRunModel)
            .where(AgentRunModel.source_chunk_id == chunk_id)
            .order_by(AgentRunModel.created_at)
        ).all()
        return [AgentRunV1.model_validate(row.payload) for row in rows]

    def count_documents(self) -> int:
        """Return total source document count."""

        return len(self._session.scalars(select(SourceDocumentModel)).all())

    def count_chunks(self) -> int:
        """Return total source chunk count."""

        return len(self._session.scalars(select(SourceChunkModel)).all())

    @staticmethod
    def _document_from_payload(payload: dict[str, object]) -> SourceDocumentV1:
        return SourceDocumentV1.model_validate(
            {key: value for key, value in payload.items() if key != _GATE1_PAYLOAD_KEY}
        )

    @staticmethod
    def _review_from_payload(
        payload: dict[str, object],
    ) -> ReviewGate1ResultV1 | None:
        review_payload = payload.get(_GATE1_PAYLOAD_KEY)
        return ReviewGate1ResultV1.model_validate(review_payload) if review_payload else None
