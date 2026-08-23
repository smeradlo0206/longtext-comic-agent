"""Agent run routes for the local development workbench."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.datastructures import State

from comic_agent.api.dependencies import (
    get_agent_run_repository,
    get_narrative_analysis_recovery_repository,
    get_narrative_analysis_repository,
    get_repository,
)
from comic_agent.config import Settings, get_settings
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import RealityLayer
from comic_agent.schemas.narrative import EventProposalBatchV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import TimelineAnalysisMode
from comic_agent.schemas.workflow import (
    AgentRunV1,
    NarrativeAnalysisCreateRequestV1,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.narrative_analysis_coordinator import NarrativeAnalysisCoordinator
from comic_agent.services.narrative_analysis_worker import NarrativeAnalysisWorker
from comic_agent.services.narrative_timeline_coordinator import NarrativeTimelineCoordinator
from comic_agent.workflows.mock_event_workflow import MockEventWorkflow
from comic_agent.workflows.narrative_analyst_workflow import NarrativeAnalystWorkflow
from comic_agent.workflows.real_event_workflow import RealEventWorkflow

router = APIRouter()

SourceRepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
AgentRunRepositoryDep = Annotated[AgentRunRepository, Depends(get_agent_run_repository)]
NarrativeAnalysisRepositoryDep = Annotated[
    NarrativeAnalysisRepository, Depends(get_narrative_analysis_repository)
]
NarrativeAnalysisRecoveryRepositoryDep = Annotated[
    NarrativeAnalysisRecoveryRepository, Depends(get_narrative_analysis_recovery_repository)
]


@router.get("/projects/{project_id}/agent-runs")
def list_project_agent_runs(
    project_id: str,
    repository: AgentRunRepositoryDep,
) -> list[dict[str, Any]]:
    """List sanitized agent runs for a project."""

    runs = repository.list_agent_runs(project_id)
    return [_agent_run_summary(run) for run in runs]


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


@router.post(
    "/projects/{project_id}/documents/{document_id}/narrative-analysis-runs",
    status_code=status.HTTP_201_CREATED,
)
def create_whole_document_analysis(
    project_id: str,
    document_id: str,
    payload: NarrativeAnalysisCreateRequestV1,
    background_tasks: BackgroundTasks,
    request: Request,
    source_repository: SourceRepositoryDep,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Create a resumable Gate 1-authorized, chapter-scoped analysis task."""

    _require_real_llm_enabled(payload.real_llm_requested, get_settings())
    try:
        coordinator = NarrativeAnalysisCoordinator(
            source_repository=source_repository,
            analysis_repository=analysis_repository,
        )
        run = coordinator.create_run(
            project_id=project_id,
            document_id=document_id,
            modes=payload.modes,
            real_llm_requested=payload.real_llm_requested,
            chapter_ids=payload.chapter_ids,
            document_revision=payload.document_revision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(
        _run_whole_document_analysis,
        request.app.state.session_factory,
        request.app.state,
        run.analysis_run_id,
        payload.real_llm_requested,
    )
    result = _analysis_run_payload(run, analysis_repository)
    result["selected_chapter_ids"] = payload.chapter_ids or [
        chapter.chapter_id for chapter in source_repository.list_document_chapters(document_id)
    ]
    return result


@router.get("/projects/{project_id}/documents/{document_id}/narrative-analysis-chapters")
def list_narrative_analysis_chapters(
    project_id: str,
    document_id: str,
    source_repository: SourceRepositoryDep,
) -> dict[str, Any]:
    """Return Gate 1 eligibility and safe chapter selection metadata."""

    try:
        return NarrativeAnalysisCoordinator(
            source_repository=source_repository,
        ).chapter_selection(project_id=project_id, document_id=document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/narrative-analysis-runs/{analysis_run_id}")
def get_whole_document_analysis(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Return sanitized progress for a whole-document analysis task."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    return _analysis_run_payload(run, analysis_repository)


@router.get("/narrative-analysis-runs/{analysis_run_id}/windows")
def list_whole_document_analysis_windows(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, list[dict[str, Any]]]:
    """Return sanitized execution audit records for each analysis window."""

    if analysis_repository.get_run(analysis_run_id) is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    return {
        "items": [
            _analysis_window_payload(window)
            for window in analysis_repository.list_windows(analysis_run_id)
        ]
    }


@router.get("/narrative-analysis-runs/{analysis_run_id}/result")
def get_whole_document_analysis_result(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Return the typed, sanitized aggregate proposal result."""

    result = analysis_repository.get_result(analysis_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisResult not available")
    return result.model_dump(mode="json")


@router.get("/narrative-analysis-runs/{analysis_run_id}/review-gate2")
def get_whole_document_review_gate2(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Return the typed deterministic Gate 2 audit only after a successful analysis run."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    if (
        str(run.status) != "SUCCEEDED"
        or run.review_gate2_result is None
        or run.review_gate2_route is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Review Gate 2 is not ready for this analysis run",
        )
    return {
        "result": run.review_gate2_result.model_dump(mode="json"),
        "route": run.review_gate2_route.model_dump(mode="json"),
    }


@router.get("/narrative-analysis-runs/{analysis_run_id}/approved-proposal-bundle")
def get_approved_proposal_bundle(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Expose a downstream bundle only when the persisted route is fully APPROVED."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    route = run.review_gate2_route
    if route is None or str(route.decision) != "APPROVED" or route.approved_proposal_bundle is None:
        raise HTTPException(status_code=409, detail="Approved proposal bundle is not available")
    return route.approved_proposal_bundle.model_dump(mode="json")


@router.get("/narrative-analysis-runs/{analysis_run_id}/recovery")
def get_narrative_analysis_recovery(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
    recovery_repository: NarrativeAnalysisRecoveryRepositoryDep,
) -> dict[str, Any]:
    """Return source-free Stage B status without exposing attempt payloads."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    attempts = recovery_repository.list_attempts(analysis_run_id)
    latest = attempts[-1] if attempts else None
    outcome = latest.outcome if latest is not None else None
    safe_codes = sorted(
        {
            str(code)
            for attempt in attempts
            for code in attempt.original_gate2_issue_codes
        }
    )
    bundle_available = bool(
        latest
        and latest.fresh_route is not None
        and str(latest.fresh_route.decision) == "APPROVED"
        and latest.fresh_route.approved_proposal_bundle is not None
    )
    return {
        "recovery_ready": bool(
            run.review_gate2_route and str(run.review_gate2_route.decision) == "REJECTED"
        ),
        "status": str(outcome.status) if outcome is not None else "NOT_STARTED",
        "route_decision": outcome.route_decision if outcome is not None else None,
        "attempt_count": len(attempts),
        "safe_issue_codes": safe_codes,
        "approved_bundle_available": bundle_available,
    }


@router.get("/narrative-analysis-runs/{analysis_run_id}/recovery/approved-proposal-bundle")
def get_recovery_approved_proposal_bundle(
    analysis_run_id: str,
    analysis_repository: NarrativeAnalysisRepositoryDep,
    recovery_repository: NarrativeAnalysisRecoveryRepositoryDep,
) -> dict[str, Any]:
    """Expose only a fresh bundle from a completed, approved recovery attempt."""

    if analysis_repository.get_run(analysis_run_id) is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    for attempt in reversed(recovery_repository.list_attempts(analysis_run_id)):
        route = attempt.fresh_route
        if (
            attempt.outcome is not None
            and str(attempt.outcome.status) == "APPROVED"
            and route is not None
            and str(route.decision) == "APPROVED"
            and route.approved_proposal_bundle is not None
        ):
            return route.approved_proposal_bundle.model_dump(mode="json")
    raise HTTPException(
        status_code=409,
        detail="Recovery approved proposal bundle is not available",
    )


@router.post(
    "/narrative-analysis-runs/{analysis_run_id}/resume", status_code=status.HTTP_202_ACCEPTED
)
def resume_whole_document_analysis(
    analysis_run_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    analysis_repository: NarrativeAnalysisRepositoryDep,
) -> dict[str, Any]:
    """Requeue only pending or failed windows after interruption or partial failure."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    _require_real_llm_enabled(run.real_llm_requested, get_settings())
    background_tasks.add_task(
        _run_whole_document_analysis,
        request.app.state.session_factory,
        request.app.state,
        analysis_run_id,
        run.real_llm_requested,
    )
    return _analysis_run_payload(run, analysis_repository)


def _run_whole_document_analysis(
    session_factory: Callable[[], Session],
    app_state: State,
    analysis_run_id: str,
    real_llm_requested: bool,
) -> None:
    """Run one task using a fresh background session after the request has closed."""

    session = session_factory()
    try:
        settings = get_settings()
        worker = NarrativeAnalysisWorker(
            settings=settings,
            source_repository=SourceRepository(session),
            agent_run_repository=AgentRunRepository(session),
            analysis_repository=NarrativeAnalysisRepository(session),
            recovery_repository=NarrativeAnalysisRecoveryRepository(session),
            provider=getattr(app_state, "narrative_analyst_provider", None),
            timeline_coordinator=NarrativeTimelineCoordinator(
                repository=TimelineGate3Repository(session),
                timeline_runner=getattr(app_state, "timeline_runner", app_state.timeline_agent),
                agent_run_repository=AgentRunRepository(session),
                timeline_mode=(
                    TimelineAnalysisMode.LLM
                    if settings.fake_pipeline_demo
                    or (real_llm_requested and settings.timeline_llm_enabled)
                    else TimelineAnalysisMode.RULES_ONLY
                ),
            ),
            allow_fake_provider=settings.fake_pipeline_demo,
        )
        worker.run_pending(analysis_run_id, real_llm_requested=real_llm_requested)
    finally:
        session.close()


def _analysis_run_payload(
    run: NarrativeAnalysisRunV1,
    analysis_repository: NarrativeAnalysisRepository,
) -> dict[str, Any]:
    """Return progress metadata only; proposal data is served by the result route."""

    payload = run.model_dump(mode="json")
    review_result = payload.pop("review_gate2_result", None)
    review_route = payload.pop("review_gate2_route", None)
    windows = analysis_repository.list_windows(run.analysis_run_id)
    payload["windows_total"] = len(windows)
    payload["windows_succeeded"] = sum(str(window.status) == "SUCCEEDED" for window in windows)
    payload["windows_failed"] = sum(str(window.status) == "FAILED" for window in windows)
    payload["windows_pending"] = sum(
        str(window.status) in {"PENDING", "RUNNING"} for window in windows
    )
    route = run.review_gate2_route
    result = run.review_gate2_result
    safe_issue_codes = sorted(
        {
            code.value
            for diagnostic in (route.recovery_diagnostics if route is not None else [])
            for code in diagnostic.issue_codes
        }
        | {
            issue.code.value
            for issue in (result.execution_issues if result is not None else [])
        }
    )
    payload.update(
        {
            "review_gate2_ready": review_result is not None and review_route is not None,
            "review_gate2_route_decision": str(route.decision) if route is not None else None,
            "review_gate2_run_id": result.review_run_id if result is not None else None,
            "review_gate2_approved_count": route.approved_count if route is not None else 0,
            "review_gate2_rejected_count": route.rejected_count if route is not None else 0,
            "review_gate2_held_count": route.held_count if route is not None else 0,
            "review_gate2_issue_codes": safe_issue_codes,
        }
    )
    return dict(payload)


def _analysis_window_payload(window: NarrativeAnalysisWindowV1) -> dict[str, Any]:
    """Return the fixed, content-free audit surface for a task window."""

    return {
        "analysis_window_id": window.analysis_window_id,
        "mode": window.mode,
        "window_index": window.window_index,
        "chunk_ids": window.chunk_ids,
        "owned_chunk_ids": window.owned_chunk_ids,
        "parent_window_id": window.parent_window_id,
        "split_reason": window.split_reason,
        "status": window.status,
        "agent_run_id": window.agent_run_id,
        "error_message": window.error_message,
        "failure_category": window.failure_category,
        "recommended_action": window.recommended_action,
        "provider_error_diagnostics": window.provider_error_diagnostics,
        "attempt_count": window.attempt_count,
        "effective_max_chars_per_chunk": window.effective_max_chars_per_chunk,
        "previous_failure_category": window.previous_failure_category,
    }


def _require_real_llm_enabled(real_llm_requested: bool, settings: Settings) -> None:
    """Fail normal-flow real tasks before planning windows when the server gate is off."""

    if real_llm_requested and not settings.enable_real_llm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Real LLM is disabled by server settings; restart the API with ENABLE_REAL_LLM=true"
            ),
        )


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
                "entity_type": evidence_item.get("entity_type"),
                "creature_subtype": evidence_item.get("creature_subtype"),
                "claim_type": evidence_item.get("claim_type"),
                "source_type": evidence_item.get("source_type"),
                "temporal_scope": evidence_item.get("temporal_scope"),
                "epistemic_status": evidence_item.get("epistemic_status"),
                "epistemic_basis": evidence_item.get("epistemic_basis"),
                "subject_resolution_status": evidence_item.get("subject_resolution_status"),
                "target_resolution_status": evidence_item.get("target_resolution_status"),
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
    entities = proposal.get("entities")
    if isinstance(entities, list):
        items = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            for evidence in entity.get("evidence_refs", []):
                items.append(
                    {
                        "proposal_id": entity.get("proposal_id"),
                        "entity_type": entity.get("entity_type"),
                        "creature_subtype": entity.get("creature_subtype"),
                        "evidence": evidence,
                    }
                )
        return items
    claims = proposal.get("claims")
    if isinstance(claims, list):
        items = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            for evidence in claim.get("evidence_refs", []):
                items.append(
                    {
                        "proposal_id": claim.get("proposal_id"),
                        "claim_type": claim.get("claim_type"),
                        "source_type": claim.get("source_type"),
                        "temporal_scope": claim.get("temporal_scope"),
                        "evidence": evidence,
                    }
                )
        return items
    states = proposal.get("states")
    if isinstance(states, list):
        items = []
        for state in states:
            if not isinstance(state, dict):
                continue
            subject = state.get("subject")
            target = state.get("target")
            for evidence in state.get("evidence_refs", []):
                items.append(
                    {
                        "proposal_id": state.get("proposal_id"),
                        "epistemic_status": state.get("epistemic_status"),
                        "epistemic_basis": state.get("epistemic_basis"),
                        "subject_resolution_status": (
                            subject.get("resolution_status") if isinstance(subject, dict) else None
                        ),
                        "target_resolution_status": (
                            target.get("resolution_status") if isinstance(target, dict) else None
                        ),
                        "evidence": evidence,
                    }
                )
        return items
    return [
        {
            "proposal_id": proposal.get("proposal_id"),
            "event_type": proposal.get("event_type"),
            "entity_type": proposal.get("entity_type"),
            "claim_type": proposal.get("claim_type"),
            "source_type": proposal.get("source_type"),
            "temporal_scope": proposal.get("temporal_scope"),
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
    first_event = proposal.events[0] if proposal and proposal.events else None
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
        "actor_resolution_status": (first_event.actor_resolution_status if first_event else None),
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
        "agent_id": run.agent_id or run.agent_name,
        "agent_name": run.agent_name,
        "source_chunk_id": run.source_chunk_id,
        "output_proposal_id": run.output_proposal_id
        or (run.output_proposal_ids[0] if run.output_proposal_ids else None),
        "status": run.status,
        "output_schema": run.output_schema,
        "input_chunk_ids": run.input_chunk_ids,
        "provider_name": provider_result.provider_name if provider_result else None,
        "provider_type": provider_result.provider_type if provider_result else None,
        "evidence_validation_passed": run.payload.get("evidence_validation_passed"),
        "created_at": run.started_at.isoformat(),
    }


def _agent_run_detail(run: AgentRunV1) -> dict[str, Any]:
    if run.source_chunk_id is not None and not run.payload and run.provider_result is None:
        return run.model_dump(mode="json")
    return {
        "agent_run_id": run.agent_run_id,
        "project_id": run.project_id,
        "agent_name": run.agent_name,
        "status": run.status,
        "input_chunk_ids": run.input_chunk_ids,
        "output_proposal_ids": run.output_proposal_ids,
        "output_schema": run.output_schema,
        "provider_result": (
            run.provider_result.model_dump(mode="json") if run.provider_result else None
        ),
        "proposal": run.payload.get("proposal"),
        "evidence_validation_passed": run.payload.get("evidence_validation_passed"),
        "error_message": run.error_message,
    }
