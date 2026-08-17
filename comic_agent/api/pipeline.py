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
    get_repository,
    get_timeline_gate3_repository,
)
from comic_agent.api.documents import import_document
from comic_agent.config import get_settings
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.services.narrative_analysis_coordinator import NarrativeAnalysisCoordinator

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
TimelineRepositoryDep = Annotated[TimelineGate3Repository, Depends(get_timeline_gate3_repository)]
UploadFileDep = Annotated[UploadFile, File(...)]

_SAFE_NARRATIVE_MODES = ["event_extraction"]


@router.post("/projects/{project_id}/pipeline-runs/import-and-analyze", response_model=None)
async def import_and_analyze(
    project_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFileDep,
    repository: RepositoryDep,
    analysis_repository: AnalysisRepositoryDep,
    project_name: Annotated[str | None, Form()] = None,
    real_llm_requested: Annotated[bool, Form()] = False,
) -> dict[str, object] | JSONResponse:
    """Import once, then schedule the established Gate 1 -> Narrative worker path."""

    _require_real_pipeline_opt_in(real_llm_requested)
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
) -> dict[str, object]:
    """Return source-free progress composed from persisted Gate and recovery artifacts."""

    run = analysis_repository.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="NarrativeAnalysisRun not found")
    gate1 = repository.get_review_gate1(run.document_id)
    route = run.review_gate2_route
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
    )
    return {
        "analysis_run_id": run.analysis_run_id,
        "project_id": run.project_id,
        "document_id": run.document_id,
        "gate1": str(gate1.decision) if gate1 is not None else "PENDING",
        "narrative": str(run.status),
        "gate2": (
            str(latest_gate2_route.decision)
            if latest_gate2_route is not None
            else "NOT_READY"
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


def _require_real_pipeline_opt_in(real_llm_requested: bool) -> None:
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


def _recovery_status(attempts: list[Any]) -> str:
    if not attempts:
        return "NOT_STARTED"
    if any(str(attempt.status) in {"RESERVED", "RUNNING", "REVIEWING"} for attempt in attempts):
        return "IN_PROGRESS"
    if any(str(attempt.outcome.status) == "APPROVED" for attempt in attempts if attempt.outcome):
        return "SUCCEEDED"
    return "STOPPED"


def _timeline_recovery_status(timeline: Any) -> str:
    if timeline is None or timeline.recovery_budget.attempts_used == 0:
        return "NOT_STARTED"
    if str(timeline.status) in {"RECOVERY_RUNNING", "PROVIDER_SUCCEEDED", "REVIEWING"}:
        return "IN_PROGRESS"
    if str(timeline.status) == "APPROVED":
        return "SUCCEEDED"
    return "STOPPED"
