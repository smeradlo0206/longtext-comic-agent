"""One-click, safe local pipeline entrypoints built from existing Gate services."""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse

from comic_agent.api.agent_runs import _require_real_llm_enabled, _run_whole_document_analysis
from comic_agent.api.dependencies import (
    get_narrative_analysis_recovery_repository,
    get_narrative_analysis_repository,
    get_provider_circuit_repository,
    get_repository,
    get_timeline_gate3_repository,
)
from comic_agent.api.documents import import_document
from comic_agent.config import get_settings
from comic_agent.providers.openai_compatible import build_openai_compatible_provider
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.provider_circuit_repository import ProviderCircuitRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.reliability import ProviderHealthResultV1, ProviderHealthStatus
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.schemas.workflow import NarrativeAnalysisRunStatus, NarrativeGate2HandoffStatus
from comic_agent.services.narrative_analysis_coordinator import NarrativeAnalysisCoordinator
from comic_agent.services.provider_health_service import ProviderHealthService

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
AnalysisRepositoryDep = Annotated[
    NarrativeAnalysisRepository,
    Depends(get_narrative_analysis_repository),
]
RecoveryRepositoryDep = Annotated[
    NarrativeAnalysisRecoveryRepository,
    Depends(get_narrative_analysis_recovery_repository),
]
TimelineRepositoryDep = Annotated[
    TimelineGate3Repository, Depends(get_timeline_gate3_repository)
]
CircuitRepositoryDep = Annotated[
    ProviderCircuitRepository, Depends(get_provider_circuit_repository)
]
UploadFileDep = Annotated[UploadFile, File(...)]

_SAFE_NARRATIVE_MODES = ["event_extraction"]


@router.get("/provider-health", response_model=ProviderHealthResultV1)
def get_provider_health(circuit_repository: CircuitRepositoryDep) -> ProviderHealthResultV1:
    """Return persisted Provider availability without probing or exposing configuration."""

    settings = get_settings()
    state = circuit_repository.get(settings.llm_provider_name)
    if state is None:
        return ProviderHealthResultV1(
            provider_key=settings.llm_provider_name,
            status=ProviderHealthStatus.AVAILABLE,
        )
    return ProviderHealthResultV1(
        provider_key=state.provider_key,
        status=state.status,
        failure_category=state.last_failure_category,
        safe_issue_codes=(
            ["PROVIDER_CIRCUIT_OPEN"] if state.status != ProviderHealthStatus.AVAILABLE else []
        ),
        next_eligible_retry_at=state.next_eligible_retry_at,
    )


@router.post("/projects/{project_id}/pipeline-runs/import-and-analyze", response_model=None)
async def import_and_analyze(
    project_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFileDep,
    repository: RepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    circuit_repository: CircuitRepositoryDep,
    project_name: Annotated[str | None, Form()] = None,
    real_llm_requested: Annotated[bool, Form()] = False,
) -> dict[str, object] | JSONResponse:
    """Import once, then schedule the established Gate 1 -> Narrative worker path."""

    _require_real_pipeline_opt_in(
        real_llm_requested,
        request=request,
        circuit_repository=circuit_repository,
    )
    _ensure_project(repository, project_id, project_name)
    imported = await import_document(project_id=project_id, file=file, repository=repository)
    if isinstance(imported, JSONResponse):
        return imported
    document = imported["document"]
    if not isinstance(document, dict) or not isinstance(document.get("document_id"), str):
        raise HTTPException(status_code=500, detail="Pipeline import did not return a document id")
    try:
        run = NarrativeAnalysisCoordinator(
            source_repository=repository,
            analysis_repository=analysis_repository,
            settings=get_settings(),
        ).create_run(
            project_id=project_id,
            document_id=document["document_id"],
            chapter_ids=None,
            modes=_SAFE_NARRATIVE_MODES,
            real_llm_requested=real_llm_requested,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(
        _run_whole_document_analysis,
        request.app.state.session_factory,
        request.app.state,
        run.analysis_run_id,
        real_llm_requested,
    )
    return {
        "project_id": project_id,
        "document_id": document["document_id"],
        "analysis_run_id": run.analysis_run_id,
        "pipeline_status": "NARRATIVE_QUEUED",
        "status_url": f"/pipeline-runs/{run.analysis_run_id}",
        "real_llm_requested": real_llm_requested,
    }


@router.get("/pipeline-runs/{analysis_run_id}")
def get_pipeline_status(
    analysis_run_id: str,
    repository: RepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    recovery_repository: RecoveryRepositoryDep,
    timeline_repository: TimelineRepositoryDep,
    circuit_repository: CircuitRepositoryDep,
) -> dict[str, object]:
    """Return source-free progress composed from persisted Gate and recovery artifacts."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    windows = analysis_repository.list_windows(analysis_run_id)
    provider_health = get_provider_health(circuit_repository)
    gate1 = repository.get_review_gate1(run.document_id)
    route = run.review_gate2_route
    aggregate = analysis_repository.get_result(analysis_run_id)
    attempts = recovery_repository.list_attempts(analysis_run_id)
    fresh_routes = [attempt.fresh_route for attempt in attempts if attempt.fresh_route is not None]
    latest_gate2_route = fresh_routes[-1] if fresh_routes else route
    timeline_route = latest_gate2_route
    bundle = timeline_route.approved_proposal_bundle if timeline_route is not None else None
    timeline = (
        timeline_repository.get_by_bundle(run.project_id, bundle.bundle_id)
        if bundle is not None
        else None
    )
    gate3_route = timeline.gate3_route if timeline is not None else None
    gate3_result = timeline.gate3_result if timeline is not None else None
    safe_codes = sorted(
        {
            str(code)
            for attempt in attempts
            for code in attempt.original_gate2_issue_codes
        }
        | set(str(code) for code in (gate3_route.safe_issue_codes if gate3_route else []))
        | set(run.gate2_handoff.safe_issue_codes if run.gate2_handoff is not None else [])
    )
    return {
        "analysis_run_id": run.analysis_run_id,
        "project_id": run.project_id,
        "document_id": run.document_id,
        "gate1": str(gate1.decision) if gate1 is not None else "PENDING",
        "narrative": str(run.status),
        "narrative_failure_summary": _narrative_failure_summary(windows),
        "batch_summary": _batch_summary(run, windows),
        "window_summary": _window_summary(windows),
        "provider_health": provider_health.model_dump(mode="json"),
        "gate2": _gate2_status(run, aggregate, latest_gate2_route),
        "gate2_handoff": (
            run.gate2_handoff.model_dump(mode="json") if run.gate2_handoff is not None else None
        ),
        "narrative_recovery": _recovery_status(attempts),
        "timeline": str(timeline.status) if timeline is not None else "NOT_READY",
        "timeline_recovery": _timeline_recovery_status(timeline),
        "gate3": str(gate3_route.route) if gate3_route is not None else "NOT_READY",
        "approved_timeline_bundle_id": (
            gate3_route.approved_timeline_bundle_id if gate3_route is not None else None
        ),
        "safe_issue_codes": safe_codes,
        "gate3_issue_count": gate3_result.issue_count if gate3_result is not None else 0,
        "narrative_recovery_attempts": len(attempts),
        "narrative_recovery_budget": (
            attempts[-1].budget_usage.model_dump(mode="json") if attempts else None
        ),
        "timeline_recovery_budget": (
            timeline.recovery_budget.model_dump(mode="json") if timeline is not None else None
        ),
    }


def _ensure_project(repository: SourceRepository, project_id: str, name: str | None) -> None:
    if repository.get_project(project_id) is not None:
        return
    display_name = (
        name.strip()
        if isinstance(name, str) and name.strip()
        else f"Local demo {project_id}"
    )
    repository.create_project(
        ProjectSpecV1(
            id=project_id,
            name=display_name,
            project_type=ProjectType.LONG_NOVEL,
            fidelity_mode=FidelityMode.CANON_STRICT,
            output_format="PAGES",
            reading_direction="LTR",
            allow_new_events=False,
            allow_new_dialogue=False,
            allow_event_reordering=False,
            allow_visual_compression=True,
            allow_dialogue_splitting=True,
            require_source_traceability=True,
            max_auto_repairs=3,
            budget_limit=None,
        )
    )


def _require_real_pipeline_opt_in(
    real_llm_requested: bool,
    *,
    request: Request,
    circuit_repository: ProviderCircuitRepository,
) -> None:
    """Reject unsafe real-provider requests before importing or scheduling work."""

    if not real_llm_requested:
        return
    settings = get_settings()
    _require_real_llm_enabled(True, settings)
    if settings.fake_pipeline_demo:
        raise HTTPException(
            status_code=409,
            detail="Real LLM cannot run while the local Fake pipeline demo is enabled",
        )
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if not api_key:
        raise HTTPException(
            status_code=409,
            detail="Real LLM requires a configured local API key",
        )
    provider = getattr(request.app.state, "narrative_analyst_provider", None)
    if provider is None:
        provider = build_openai_compatible_provider(settings)
    result = ProviderHealthService(settings=settings, repository=circuit_repository).preflight(
        provider_key=settings.llm_provider_name,
        provider=provider,
    )
    if str(result.status) != "AVAILABLE":
        raise HTTPException(status_code=409, detail=result.model_dump(mode="json"))


def _gate2_status(run: Any, aggregate: Any, route: Any) -> str:
    """Separate deterministic Gate 2 handoff progress from its eventual route."""

    if route is not None:
        return str(route.decision)
    if run.status != NarrativeAnalysisRunStatus.SUCCEEDED or aggregate is None:
        return "NOT_READY"
    handoff = run.gate2_handoff
    if handoff is None or handoff.status == NarrativeGate2HandoffStatus.PENDING:
        return "GATE2_PENDING"
    if handoff.status == NarrativeGate2HandoffStatus.RUNNING:
        return "GATE2_RECOVERING"
    if handoff.status == NarrativeGate2HandoffStatus.FAILED:
        return "GATE2_FAILED"
    return "GATE2_PENDING"


def _recovery_status(attempts: list[Any]) -> str:
    if not attempts:
        return "NOT_STARTED"
    if any(str(attempt.status) in {"RESERVED", "RUNNING", "REVIEWING"} for attempt in attempts):
        return "IN_PROGRESS"
    if any(str(attempt.outcome.status) == "APPROVED" for attempt in attempts if attempt.outcome):
        return "SUCCEEDED"
    return "STOPPED"


def _narrative_failure_summary(windows: list[Any]) -> dict[str, object] | None:
    """Expose only persisted, source-free failure categories for the one-click Console."""

    failed_windows = [
        window
        for window in windows
        if str(window.status) in {"FAILED", "EXHAUSTED"}
    ]
    if not failed_windows:
        return None
    categories = sorted(
        {
            str(window.failure_category)
            for window in failed_windows
            if isinstance(window.failure_category, str) and window.failure_category
        }
    )
    recommended_actions = sorted(
        {
            str(window.recommended_action)
            for window in failed_windows
            if isinstance(window.recommended_action, str) and window.recommended_action
        }
    )
    return {
        "failed_window_count": len(failed_windows),
        "failure_categories": categories,
        "recommended_actions": recommended_actions,
    }


def _window_summary(windows: list[Any]) -> dict[str, object]:
    """Summarize only execution states/budgets; never return SourceChunk content."""

    counts: dict[str, int] = {}
    retry_times = []
    attempts_used = 0
    provider_requests_used = 0
    elapsed_seconds_used = 0
    output_tokens_used = 0
    for window in windows:
        status = str(window.status)
        counts[status] = counts.get(status, 0) + 1
        attempts_used += int(window.attempt_count)
        provider_requests_used += int(window.provider_request_count)
        elapsed_seconds_used += int(window.elapsed_seconds_used)
        output_tokens_used += int(window.output_tokens_used)
        if window.next_eligible_retry_at is not None:
            retry_times.append(window.next_eligible_retry_at)
    return {
        "total": len(windows),
        "status_counts": counts,
        "attempts_used": attempts_used,
        "provider_requests_used": provider_requests_used,
        "elapsed_seconds_used": elapsed_seconds_used,
        "output_tokens_used": output_tokens_used,
        "next_eligible_retry_at": min(retry_times).isoformat() if retry_times else None,
    }


def _batch_summary(run: Any, windows: list[Any]) -> dict[str, object]:
    """Expose aggregate batch progress without returning chunk ids or source content."""

    counts: dict[str, int] = {}
    for batch in run.batches:
        statuses = [str(window.status) for window in windows if window.batch_id == batch.batch_id]
        if not statuses:
            status = "PLANNED"
        elif any(
            status in {"RESERVED", "RUNNING", "PROVIDER_SUCCEEDED", "REVIEWING"}
            for status in statuses
        ):
            status = "RUNNING"
        elif any(status == "FAILED" for status in statuses):
            status = "FAILED"
        elif all(status == "SUCCEEDED" for status in statuses):
            status = "SUCCEEDED"
        elif all(status in {"SPLIT", "EXHAUSTED"} for status in statuses):
            status = "EXHAUSTED"
        else:
            status = "PLANNED"
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(run.batches), "status_counts": counts}


def _timeline_recovery_status(timeline: Any) -> str:
    if timeline is None or timeline.recovery_budget.attempts_used == 0:
        return "NOT_STARTED"
    if str(timeline.status) in {"RECOVERY_RUNNING", "PROVIDER_SUCCEEDED", "REVIEWING"}:
        return "IN_PROGRESS"
    if str(timeline.status) == "APPROVED":
        return "SUCCEEDED"
    return "STOPPED"
