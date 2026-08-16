"""Project-scoped API entry point for deterministic and LLM timeline analysis."""

import json
from collections.abc import Iterator
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.api.dependencies import get_repository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import TimelineAnalysisInputV1, TimelineAnalysisProposalV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.id_service import checksum_text

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]


def get_timeline_agent(request: Request) -> TimelineAgent:
    """Return the app-owned agent so tests can replace its provider."""

    return cast(TimelineAgent, request.app.state.timeline_agent)


TimelineAgentDep = Annotated[TimelineAgent, Depends(get_timeline_agent)]


@router.post(
    "/projects/{project_id}/timeline/analyze",
    response_model=TimelineAnalysisProposalV1,
)
def analyze_timeline(
    project_id: str,
    analysis_input: TimelineAnalysisInputV1,
    repository: RepositoryDep,
    timeline_agent: TimelineAgentDep,
) -> TimelineAnalysisProposalV1:
    """Analyze and persist candidates with pre-call caching and failure audit records."""

    if analysis_input.project_id != project_id:
        raise HTTPException(status_code=409, detail="Timeline analysis project mismatch")
    chunks = _resolve_source_chunks(analysis_input, project_id, repository)
    input_hash = _cache_key(analysis_input, chunks, timeline_agent)
    cached = repository.get_timeline_analysis_by_input_hash(project_id, input_hash)
    if cached is not None:
        return cached

    try:
        proposal = timeline_agent.run(analysis_input, source_chunks=chunks.values())
        validator = CommitService(repository)
        for relation in proposal.temporal_relations:
            validator.validate_temporal_relation_evidence(relation, project_id)
        stored_proposal = repository.save_timeline_analysis(proposal, input_hash)
    except (TimeoutError, ValueError, RuntimeError) as exc:
        repository.save_agent_run(
            AgentRunV1(
                agent_run_id=f"agent-run-{uuid4().hex}",
                project_id=project_id,
                agent_name=TimelineAgent.spec.agent_id,
                agent_id=TimelineAgent.spec.agent_id,
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.FAILED,
                error_message=str(exc),
            )
        )
        raise HTTPException(status_code=422, detail=f"Timeline analysis failed: {exc}") from exc

    repository.save_agent_run(
        AgentRunV1(
            agent_run_id=f"agent-run-{uuid4().hex}",
            project_id=project_id,
            agent_id=TimelineAgent.spec.agent_id,
            agent_name=TimelineAgent.spec.agent_id,
            input_chunk_ids=sorted(chunks),
            status=AgentRunStatus.SUCCEEDED,
            output_proposal_id=stored_proposal.proposal_id,
            output_proposal_ids=[stored_proposal.proposal_id],
            output_schema="TimelineAnalysisProposalV1",
        )
    )
    return stored_proposal


@router.get(
    "/projects/{project_id}/timeline/analyses",
    response_model=list[TimelineAnalysisProposalV1],
)
def list_timeline_analyses(
    project_id: str,
    repository: RepositoryDep,
) -> list[TimelineAnalysisProposalV1]:
    """List persisted candidate analyses for one project."""

    return repository.list_timeline_analyses(project_id)


@router.get(
    "/projects/{project_id}/timeline/analyses/{proposal_id}",
    response_model=TimelineAnalysisProposalV1,
)
def get_timeline_analysis(
    project_id: str,
    proposal_id: str,
    repository: RepositoryDep,
) -> TimelineAnalysisProposalV1:
    """Return one persisted candidate analysis owned by the path project."""

    proposal = repository.get_timeline_analysis(project_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Timeline analysis not found")
    return proposal


@router.get("/projects/{project_id}/agent-runs", response_model=list[AgentRunV1])
def list_project_agent_runs(
    project_id: str,
    repository: RepositoryDep,
) -> list[AgentRunV1]:
    """List single-chunk and aggregate agent executions for one project."""

    return repository.list_agent_runs_for_project(project_id)


def _resolve_source_chunks(
    analysis_input: TimelineAnalysisInputV1,
    project_id: str,
    repository: SourceRepository,
) -> dict[str, SourceChunkV1]:
    """Resolve request evidence to project-owned chunks before assembling agent context."""

    chunks: dict[str, SourceChunkV1] = {}
    for evidence_ref in _evidence_refs(analysis_input):
        chunk = repository.get_chunk(evidence_ref.chunk_id)
        if chunk is None or chunk.project_id != project_id:
            raise HTTPException(status_code=409, detail="Timeline analysis project mismatch")
        chunks[chunk.chunk_id] = chunk
    return chunks


def _cache_key(
    analysis_input: TimelineAnalysisInputV1,
    chunks: dict[str, SourceChunkV1],
    timeline_agent: TimelineAgent,
) -> str:
    """Include exact evidence, prompt and agent identity before making a model call."""

    source_chunks = [
        {"chunk_id": chunk_id, "text": chunk.text, "checksum": chunk.checksum}
        for chunk_id, chunk in sorted(chunks.items())
    ]
    payload = {
        "analysis_input": analysis_input.model_dump(mode="json"),
        "source_chunks": source_chunks,
        "timeline_agent": timeline_agent.cache_identity,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return checksum_text(serialized)


def _evidence_refs(analysis_input: TimelineAnalysisInputV1) -> Iterator[EvidenceRefV1]:
    """Yield evidence from every concrete proposal type in the request."""

    for event_proposal in analysis_input.event_proposals:
        yield from event_proposal.evidence_refs
    for claim_proposal in analysis_input.claim_proposals:
        yield from claim_proposal.evidence_refs
    for state_change_proposal in analysis_input.state_change_proposals:
        yield from state_change_proposal.evidence_refs
