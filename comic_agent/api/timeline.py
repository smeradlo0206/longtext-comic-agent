"""Project-scoped API entry point for deterministic and LLM timeline analysis."""

import json
from collections.abc import Iterator
from typing import Annotated, cast
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.api.dependencies import (
    get_repository,
    get_timeline_gate3_repository,
)
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    Gate3HumanReviewInputV1,
    Gate3HumanReviewRequestV1,
    Gate3HumanReviewResponseV1,
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
)
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.gate3_human_review_service import (
    Gate3HumanReviewConflictError,
    Gate3HumanReviewNotFoundError,
    Gate3HumanReviewService,
)
from comic_agent.services.id_service import checksum_text

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]


def get_timeline_agent(request: Request) -> TimelineAgent:
    """Return the app-owned agent so tests can replace its provider."""

    return cast(TimelineAgent, request.app.state.timeline_agent)


TimelineAgentDep = Annotated[TimelineAgent, Depends(get_timeline_agent)]
TimelineGate3RepositoryDep = Annotated[
    TimelineGate3Repository,
    Depends(get_timeline_gate3_repository),
]


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
    except (httpx.HTTPError, TimeoutError, ValueError, RuntimeError) as exc:
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


@router.get("/projects/{project_id}/timeline-gate3/{source_bundle_id}")
def get_timeline_gate3_summary(
    project_id: str,
    source_bundle_id: str,
    repository: TimelineGate3RepositoryDep,
) -> dict[str, object]:
    """Return content-free Gate 2 -> Timeline -> Gate 3 progress metadata."""

    run = repository.get_by_bundle(project_id, source_bundle_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="Timeline is not ready for this approved bundle",
        )
    route = run.gate3_route
    return {
        "source_approved_proposal_bundle_id": run.source_approved_proposal_bundle_id,
        "timeline_run_id": run.timeline_run_id,
        "timeline_status": run.status,
        "timeline_provider_request_count": run.provider_request_count,
        "gate3_ready": run.gate3_result is not None and route is not None,
        "gate3_route": route.route if route is not None else None,
        "gate3_issue_count": run.gate3_result.issue_count if run.gate3_result else 0,
        "gate3_safe_issue_codes": route.safe_issue_codes if route is not None else [],
    }


@router.get("/projects/{project_id}/timeline-gate3/{source_bundle_id}/review")
def get_timeline_gate3_review(
    project_id: str,
    source_bundle_id: str,
    repository: TimelineGate3RepositoryDep,
) -> dict[str, object]:
    """Return typed review fields after removing source/provider payloads."""

    run = repository.get_by_bundle(project_id, source_bundle_id)
    if run is None or run.gate3_result is None or run.gate3_route is None:
        raise HTTPException(status_code=409, detail="Timeline Gate 3 review is not ready")
    result = run.gate3_result.model_dump(mode="json")
    result.pop("evidence_refs", None)
    for issue in result.get("issues", []):
        if isinstance(issue, dict):
            issue.pop("evidence_refs", None)
    route = run.gate3_route.model_dump(
        mode="json",
        exclude={"approved_timeline_bundle"},
    )
    return {"result": result, "route": route}


@router.get("/projects/{project_id}/timeline-gate3/{source_bundle_id}/approved-bundle")
def get_approved_timeline_bundle(
    project_id: str,
    source_bundle_id: str,
    repository: TimelineGate3RepositoryDep,
) -> dict[str, object]:
    """Expose only Gate 3's fresh approved Timeline bundle."""

    run = repository.get_by_bundle(project_id, source_bundle_id)
    if run is None or run.approved_timeline_bundle is None:
        raise HTTPException(status_code=409, detail="Approved Timeline bundle is unavailable")
    return _safe_bundle_payload(run.approved_timeline_bundle.model_dump(mode="json"))


@router.post(
    "/projects/{project_id}/timeline-gate3/runs/{gate3_run_id}/review",
    response_model=Gate3HumanReviewResponseV1,
)
def review_timeline_gate3_run(
    project_id: str,
    gate3_run_id: str,
    review: Gate3HumanReviewRequestV1,
    repository: TimelineGate3RepositoryDep,
) -> Gate3HumanReviewResponseV1:
    """Resolve and finalize the existing project-owned Gate 3 run."""

    review_input = Gate3HumanReviewInputV1(
        gate3_run_id=gate3_run_id,
        resolution=review.resolution,
        reviewer_id=review.reviewer_id,
        note=review.note,
    )
    try:
        run = Gate3HumanReviewService(repository).review_gate3_run(
            review_input,
            project_id=project_id,
        )
    except Gate3HumanReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Timeline Gate 3 run not found") from exc
    except Gate3HumanReviewConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Timeline Gate 3 run cannot be reviewed",
        ) from exc
    result = run.gate3_result
    if result is None or result.human_review is None or result.effective_decision is None:
        raise RuntimeError("Human-reviewed Gate 3 result is incomplete")
    bundle = run.approved_timeline_bundle
    return Gate3HumanReviewResponseV1(
        gate3_run_id=run.timeline_run_id,
        project_id=run.project_id,
        status=run.status,
        automated_decision=result.decision,
        effective_decision=result.effective_decision,
        human_review=result.human_review,
        approved_timeline_bundle_id=bundle.bundle_id if bundle is not None else None,
        approved_timeline_bundle_available=bundle is not None,
    )


def _safe_bundle_payload(payload: dict[str, object]) -> dict[str, object]:
    """Keep typed identifiers/provenance while withholding source excerpts from read APIs."""

    def scrub(value: object) -> object:
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: scrub(item)
            for key, item in value.items()
            if key not in {"quote_text", "prompt", "provider_response"}
        }

    safe = scrub(payload)
    if not isinstance(safe, dict):
        raise RuntimeError("Approved Timeline bundle payload must be an object")
    return safe


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
