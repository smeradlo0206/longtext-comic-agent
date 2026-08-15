"""Document import and source query routes."""

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from comic_agent.agents.mocks import MockEventAgent
from comic_agent.api.dependencies import get_repository
from comic_agent.config import get_settings
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.review import SourceReviewDecision
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.review_gate1_service import (
    ReviewGate1Service,
    build_review_gate1_input,
)

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
UploadFileDep = Annotated[UploadFile, File(...)]


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: str, repository: RepositoryDep) -> list[dict[str, object]]:
    """List safe document-selection metadata without source text or storage paths."""

    return [
        {
            "document_id": document.document_id,
            "filename": document.filename,
            "revision": document.revision,
        }
        for document in repository.list_documents(project_id)
    ]


@router.post("/projects/{project_id}/documents/import", status_code=status.HTTP_201_CREATED)
async def import_document(
    project_id: str,
    file: UploadFileDep,
    repository: RepositoryDep,
) -> Any:
    """Import a TXT document through multipart upload."""

    raw = await file.read()
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "source.txt"
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=415, detail="Only TXT import is implemented in phase 1")
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="TXT file must be UTF-8 encoded") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(text) > get_settings().internal_demo_max_import_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="TXT exceeds demo import character limit",
        )
    parsed = DocumentParser().parse_txt(
        project_id=project_id,
        filename=filename,
        text=text,
        mime_type=content_type,
    )
    gate1 = ReviewGate1Service().review(
        build_review_gate1_input(parsed=parsed, normalized_text=text)
    )
    response_gate1 = gate1.model_dump(mode="json")
    if gate1.decision != SourceReviewDecision.APPROVED:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "status": "gate1_blocked",
                "gate1": response_gate1,
                "approved_chunk_bundle": None,
            },
        )
    result = repository.import_reviewed_document(parsed, gate1)
    return {
        "status": result.status,
        "document": result.document.model_dump(mode="json"),
        "chapters_count": len(result.chapters),
        "chunks_count": len(result.chunks),
        "gate1": response_gate1,
        "approved_chunk_bundle": gate1.approved_chunk_bundle.model_dump(mode="json")
        if gate1.approved_chunk_bundle is not None
        else None,
        "analysis_eligible": True,
    }


@router.get("/chapters/{chapter_id}/chunks", response_model=list[SourceChunkV1])
def list_chapter_chunks(
    chapter_id: str,
    repository: RepositoryDep,
) -> list[SourceChunkV1]:
    """List chunks for a chapter."""

    return repository.list_chunks_for_chapter(chapter_id)


@router.get("/chunks/{chunk_id}", response_model=SourceChunkV1)
def get_chunk(
    chunk_id: str,
    repository: RepositoryDep,
) -> SourceChunkV1:
    """Return one source chunk."""

    chunk = repository.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return chunk


@router.post("/chunks/{chunk_id}/mock-event", response_model=EventProposalV1)
def extract_mock_event(
    chunk_id: str,
    repository: RepositoryDep,
) -> EventProposalV1:
    """Create a candidate proposal and record the deterministic agent execution."""

    chunk = repository.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    proposal = MockEventAgent().run(chunk)
    CommitService(repository).validate_story_proposal_evidence(proposal)
    stored_proposal = repository.save_event_proposal(
        proposal=proposal,
        source_chunk=chunk,
        agent_id=MockEventAgent.spec.agent_id,
    )
    repository.save_agent_run(
        AgentRunV1(
            agent_run_id=f"agent-run-{uuid4().hex}",
            project_id=chunk.project_id,
            source_chunk_id=chunk.chunk_id,
            agent_id=MockEventAgent.spec.agent_id,
            agent_name=MockEventAgent.spec.agent_id,
            input_chunk_ids=[chunk.chunk_id],
            status=AgentRunStatus.SUCCEEDED,
            output_proposal_id=stored_proposal.proposal_id,
            output_proposal_ids=[stored_proposal.proposal_id],
            output_schema="EventProposalV1",
        )
    )
    return stored_proposal


@router.get("/event-proposals/{proposal_id}", response_model=EventProposalV1)
def get_event_proposal(
    proposal_id: str,
    repository: RepositoryDep,
) -> EventProposalV1:
    """Return a stored candidate event proposal by id."""

    proposal = repository.get_event_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Event proposal not found")
    return proposal


@router.get("/chunks/{chunk_id}/event-proposals", response_model=list[EventProposalV1])
def list_chunk_event_proposals(
    chunk_id: str,
    repository: RepositoryDep,
) -> list[EventProposalV1]:
    """List stored candidate event proposals for a source chunk."""

    if repository.get_chunk(chunk_id) is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return repository.list_event_proposals_for_chunk(chunk_id)


@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunV1)
def get_agent_run(
    agent_run_id: str,
    repository: RepositoryDep,
) -> AgentRunV1:
    """Return one stored agent execution trace."""

    agent_run = repository.get_agent_run(agent_run_id)
    if agent_run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return agent_run


@router.get("/chunks/{chunk_id}/agent-runs", response_model=list[AgentRunV1])
def list_chunk_agent_runs(
    chunk_id: str,
    repository: RepositoryDep,
) -> list[AgentRunV1]:
    """List agent execution traces for a source chunk."""

    if repository.get_chunk(chunk_id) is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return repository.list_agent_runs_for_chunk(chunk_id)
