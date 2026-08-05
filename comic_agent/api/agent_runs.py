"""Agent run routes for the local development workbench."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from comic_agent.api.demo import require_demo_access_code
from comic_agent.api.dependencies import get_agent_run_repository, get_repository
from comic_agent.config import get_settings
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import RealityLayer
from comic_agent.schemas.narrative import EventProposalBatchV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import AgentRunV1
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.workflows.mock_event_workflow import MockEventWorkflow
from comic_agent.workflows.narrative_analyst_workflow import NarrativeAnalystWorkflow
from comic_agent.workflows.real_event_workflow import RealEventWorkflow

router = APIRouter()

SourceRepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
AgentRunRepositoryDep = Annotated[AgentRunRepository, Depends(get_agent_run_repository)]


@router.get("/projects/{project_id}/agent-runs")
def list_project_agent_runs(
    project_id: str,
    repository: AgentRunRepositoryDep,
) -> dict[str, list[dict[str, Any]]]:
    """List sanitized agent runs for a project."""

    runs = repository.list_agent_runs(project_id)
    return {"items": [_agent_run_summary(run) for run in runs]}


@router.post(
    "/projects/{project_id}/agent-runs/mock-event",
    status_code=status.HTTP_201_CREATED,
)
def run_mock_event(
    project_id: str,
    payload: Annotated[dict[str, Any], Body()],
    source_repository: SourceRepositoryDep,
    agent_run_repository: AgentRunRepositoryDep,
) -> dict[str, Any]:
    """Run the deterministic mock Event workflow over selected chunks."""

    chunk_ids = [str(chunk_id) for chunk_id in payload.get("chunk_ids", [])]
    if not chunk_ids:
        raise HTTPException(status_code=400, detail="chunk_ids is required")

    chunks = []
    for chunk_id in chunk_ids:
        chunk = source_repository.get_chunk(chunk_id)
        if chunk is None or chunk.project_id != project_id:
            raise HTTPException(status_code=404, detail="Chunk not found")
        chunks.append(chunk)

    provider = MockLLMProvider(
        response=_mock_event_response(project_id, chunks[0].chunk_id, chunks[0].text)
    )
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=provider,
    )
    result = workflow.run(project_id=project_id, chunk_ids=chunk_ids)
    return {
        "agent_run_id": result.agent_run.agent_run_id,
        "status": result.agent_run.status,
        "proposal": result.proposal.model_dump(mode="json") if result.proposal else None,
        "evidence_validation_passed": result.agent_run.payload.get("evidence_validation_passed"),
        "error_message": result.agent_run.error_message,
    }


@router.post(
    "/projects/{project_id}/agent-runs/real-event",
    status_code=status.HTTP_201_CREATED,
)
def run_real_event(
    project_id: str,
    payload: Annotated[dict[str, Any], Body()],
    source_repository: SourceRepositoryDep,
    agent_run_repository: AgentRunRepositoryDep,
    request: Request,
    _: Annotated[None, Depends(require_demo_access_code)],
) -> dict[str, Any]:
    """Run the real Event workflow for the internal hosted demo."""

    settings = get_settings()
    chunk_ids = [str(chunk_id) for chunk_id in payload.get("chunk_ids", [])]
    if not chunk_ids:
        raise HTTPException(status_code=400, detail="chunk_ids is required")
    if len(chunk_ids) > settings.internal_demo_max_real_event_chunks_per_run:
        raise HTTPException(status_code=400, detail="real-event chunk_ids cannot exceed 3")

    chunks = _project_chunks(source_repository, project_id, chunk_ids)
    provider = getattr(request.app.state, "real_event_provider", None)
    workflow = RealEventWorkflow(
        settings=settings,
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=provider,
    )
    result = workflow.run(project_id=project_id, chunk_ids=chunk_ids)
    return _real_event_summary(result.agent_run, result.proposal, chunks)


@router.post(
    "/projects/{project_id}/agent-runs/narrative-analyst",
    status_code=status.HTTP_201_CREATED,
)
def run_narrative_analyst(
    project_id: str,
    payload: Annotated[dict[str, Any], Body()],
    source_repository: SourceRepositoryDep,
    agent_run_repository: AgentRunRepositoryDep,
    request: Request,
    _: Annotated[None, Depends(require_demo_access_code)],
) -> dict[str, Any]:
    """Run the unified NarrativeAnalyst console workflow."""

    settings = get_settings()
    mode = str(payload.get("mode", ""))
    chunk_ids_payload = payload.get("chunk_ids")
    chunk_ids = (
        [str(chunk_id) for chunk_id in chunk_ids_payload]
        if isinstance(chunk_ids_payload, list)
        else None
    )
    workflow = NarrativeAnalystWorkflow(
        settings=settings,
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=getattr(request.app.state, "narrative_analyst_provider", None),
    )
    try:
        result = workflow.run(
            project_id=project_id,
            mode=mode,
            chunk_ids=chunk_ids,
            chunk_limit=int(payload.get("chunk_limit", 3)),
            chunk_offset=int(payload.get("chunk_offset", 0)),
            max_chars_per_chunk=int(payload.get("max_chars_per_chunk", 1200)),
            real_llm_requested=bool(payload.get("real_llm_requested", False)),
        )
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.response_payload()


@router.get("/agent-runs/{agent_run_id}")
def get_agent_run(
    agent_run_id: str,
    repository: AgentRunRepositoryDep,
) -> dict[str, Any]:
    """Return a sanitized AgentRun detail."""

    run = repository.get_agent_run(agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")
    return _agent_run_detail(run)


@router.get("/agent-runs/{agent_run_id}/evidence")
def get_agent_run_evidence(
    agent_run_id: str,
    source_repository: SourceRepositoryDep,
    agent_run_repository: AgentRunRepositoryDep,
) -> dict[str, list[dict[str, Any]]]:
    """Return short evidence snippets for one AgentRun."""

    run = agent_run_repository.get_agent_run(agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AgentRun not found")

    proposal = run.payload.get("proposal")
    evidence_refs = _proposal_evidence_refs(proposal)
    items = []
    for evidence_item in evidence_refs:
        evidence = evidence_item["evidence"]
        if not isinstance(evidence, dict):
            continue
        chunk_id = str(evidence.get("chunk_id", ""))
        quote = evidence.get("quote_text")
        quote_text = str(quote) if quote is not None else ""
        chunk = source_repository.get_chunk(chunk_id)
        validation_status = "failed"
        char_start = evidence.get("quote_start")
        char_end = evidence.get("quote_end")
        if chunk is not None and quote_text:
            index = chunk.text.find(quote_text)
            if index >= 0:
                validation_status = "passed"
                base = chunk.char_start or 0
                char_start = base + index
                char_end = char_start + len(quote_text)
        items.append(
            {
                "proposal_id": evidence_item.get("proposal_id"),
                "event_type": evidence_item.get("event_type"),
                "chunk_id": chunk_id,
                "quote": quote_text[:40],
                "char_start": char_start,
                "char_end": char_end,
                "validation_status": validation_status,
            }
        )
    return {"items": items}


def _proposal_evidence_refs(proposal: object) -> list[dict[str, Any]]:
    if not isinstance(proposal, dict):
        return []
    events = proposal.get("events")
    if isinstance(events, list):
        items: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            for evidence in event.get("evidence_refs", []):
                items.append(
                    {
                        "proposal_id": event.get("proposal_id"),
                        "event_type": event.get("event_type"),
                        "evidence": evidence,
                    }
                )
        return items
    return [
        {
            "proposal_id": proposal.get("proposal_id"),
            "event_type": proposal.get("event_type"),
            "evidence": evidence,
        }
        for evidence in proposal.get("evidence_refs", [])
    ]


def _project_chunks(
    source_repository: SourceRepository,
    project_id: str,
    chunk_ids: list[str],
) -> list[SourceChunkV1]:
    chunks = []
    for chunk_id in chunk_ids:
        chunk = source_repository.get_chunk(chunk_id)
        if chunk is None or chunk.project_id != project_id:
            raise HTTPException(status_code=404, detail="Chunk not found")
        chunks.append(chunk)
    return chunks


def _real_event_summary(
    agent_run: AgentRunV1,
    proposal: EventProposalBatchV1 | None,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    provider_result = agent_run.provider_result
    first_event = proposal.events[0] if proposal else None
    summary: dict[str, Any] = {
        "agent_run_id": agent_run.agent_run_id,
        "agent_run_status": agent_run.status,
        "provider_result_id": agent_run.provider_result_id,
        "provider_success": provider_result.success if provider_result else None,
        "output_schema": agent_run.output_schema,
        "schema_validation_passed": proposal is not None,
        "batch_id": proposal.batch_id if proposal else None,
        "events_count": len(proposal.events) if proposal else None,
        "event_proposal_ids": [event.proposal_id for event in proposal.events] if proposal else [],
        "proposal_id": first_event.proposal_id if first_event else None,
        "confidence": first_event.confidence if first_event else None,
        "actor_resolution_status": (
            first_event.actor_resolution_status if first_event else None
        ),
        "evidence_validation_passed": agent_run.payload.get("evidence_validation_passed"),
        "evidence_chunk_id": None,
        "quote_matched": None,
        "char_range_matched": None,
        "error_message": agent_run.error_message,
    }
    if first_event is None or not first_event.evidence_refs:
        return summary

    evidence = first_event.evidence_refs[0]
    summary["evidence_chunk_id"] = evidence.chunk_id
    evidence_chunk = next(
        (chunk for chunk in selected_chunks if chunk.chunk_id == evidence.chunk_id),
        None,
    )
    if evidence_chunk is None:
        summary["quote_matched"] = False if evidence.quote_text is not None else None
        summary["char_range_matched"] = False if evidence.quote_start is not None else None
        return summary

    if evidence.quote_text is not None:
        summary["quote_matched"] = evidence.quote_text in evidence_chunk.text
    has_range = evidence.quote_start is not None and evidence.quote_end is not None
    if has_range:
        assert evidence.quote_start is not None
        assert evidence.quote_end is not None
        range_in_bounds = (
            0 <= evidence.quote_start <= evidence.quote_end <= len(evidence_chunk.text)
        )
        summary["char_range_matched"] = (
            range_in_bounds
            and evidence_chunk.text[evidence.quote_start : evidence.quote_end]
            == evidence.quote_text
        )
    return summary


def _mock_event_response(project_id: str, chunk_id: str, chunk_text: str) -> dict[str, Any]:
    quote = _short_quote(chunk_text)
    seed = checksum_text(f"{project_id}:{chunk_id}:{quote}")
    return {
        "proposal_id": stable_id("proposal", seed),
        "event_type": "mock_source_event",
        "summary": "Mock event proposal generated from the selected source chunk.",
        "participant_ids": [],
        "actor_resolution_status": "UNKNOWN",
        "location_id": None,
        "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
        "confidence": 0.8,
        "reality_layer": RealityLayer.PRIMARY,
    }


def _short_quote(text: str) -> str:
    compact = text.strip()
    return compact[: min(8, len(compact))]


def _agent_run_summary(run: AgentRunV1) -> dict[str, Any]:
    provider_result = run.provider_result
    return {
        "agent_run_id": run.agent_run_id,
        "project_id": run.project_id,
        "agent_name": run.agent_name,
        "status": run.status,
        "output_schema": run.output_schema,
        "input_chunk_ids": run.input_chunk_ids,
        "provider_name": provider_result.provider_name if provider_result else None,
        "provider_type": provider_result.provider_type if provider_result else None,
        "evidence_validation_passed": run.payload.get("evidence_validation_passed"),
        "created_at": run.started_at.isoformat(),
    }


def _agent_run_detail(run: AgentRunV1) -> dict[str, Any]:
    return {
        "agent_run_id": run.agent_run_id,
        "project_id": run.project_id,
        "agent_name": run.agent_name,
        "status": run.status,
        "input_chunk_ids": run.input_chunk_ids,
        "output_schema": run.output_schema,
        "provider_result": (
            run.provider_result.model_dump(mode="json") if run.provider_result else None
        ),
        "proposal": run.payload.get("proposal"),
        "evidence_validation_passed": run.payload.get("evidence_validation_passed"),
        "error_message": run.error_message,
    }
