"""One-click, safe local pipeline entrypoints built from existing Gate services."""

import json
from datetime import UTC, datetime
from time import sleep
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
from starlette.datastructures import State

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
from comic_agent.schemas.reliability import (
    ProviderHealthResultV1,
    ProviderHealthStatus,
    StructuredOutputMode,
)
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.schemas.workflow import (
    NarrativeAnalysisRunStatus,
    NarrativeGate2HandoffStatus,
    NarrativePipelinePhase,
)
from comic_agent.services.narrative_analysis_coordinator import (
    DEFAULT_NARRATIVE_ANALYST_MODES,
    NarrativeAnalysisCoordinator,
)
from comic_agent.services.provider_capability_service import ProviderCapabilityService
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
TimelineRepositoryDep = Annotated[TimelineGate3Repository, Depends(get_timeline_gate3_repository)]
CircuitRepositoryDep = Annotated[
    ProviderCircuitRepository, Depends(get_provider_circuit_repository)
]
UploadFileDep = Annotated[UploadFile, File(...)]

_SAFE_NARRATIVE_MODES = list(DEFAULT_NARRATIVE_ANALYST_MODES)
_SUPPORTED_NARRATIVE_MODES = frozenset(DEFAULT_NARRATIVE_ANALYST_MODES)


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
    project_name: Annotated[str | None, Form()] = None,
    real_llm_requested: Annotated[bool, Form()] = False,
    narrative_modes: Annotated[str | None, Form()] = None,
) -> dict[str, object] | JSONResponse:
    """Import once, then schedule the established Gate 1 -> Narrative worker path."""

    try:
        selected_modes = _parse_narrative_modes(narrative_modes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            modes=selected_modes,
            real_llm_requested=real_llm_requested,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(
        _run_pipeline_background,
        request.app.state.session_factory,
        request.app.state,
        run.analysis_run_id,
        real_llm_requested,
    )
    return {
        "project_id": project_id,
        "document_id": document["document_id"],
        "analysis_run_id": run.analysis_run_id,
        "pipeline_status": "QUEUED",
        "pipeline_phase": str(run.pipeline_phase),
        "status_url": f"/pipeline-runs/{run.analysis_run_id}",
        "real_llm_requested": real_llm_requested,
    }


def _parse_narrative_modes(value: str | None) -> list[str]:
    """Use all supported modes by default and validate explicit bounded requests."""

    if value is None:
        return list(_SAFE_NARRATIVE_MODES)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("narrative_modes must be a JSON array") from exc
    if (
        not isinstance(decoded, list)
        or not decoded
        or not all(isinstance(item, str) for item in decoded)
    ):
        raise ValueError("narrative_modes must be a non-empty JSON string array")
    modes = [item for item in decoded]
    if len(set(modes)) != len(modes):
        raise ValueError("narrative_modes must be distinct")
    unsupported = [mode for mode in modes if mode not in _SUPPORTED_NARRATIVE_MODES]
    if unsupported:
        raise ValueError("narrative_modes contains an unsupported mode")
    return modes


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
    latest_gate2_route = _latest_approved_recovery_route(attempts) or route
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
        set(run.pipeline_safe_issue_codes)
        | _gate2_safe_issue_codes(run.review_gate2_result)
        | {str(code) for attempt in attempts for code in attempt.original_gate2_issue_codes}
        | set(str(code) for code in (gate3_route.safe_issue_codes if gate3_route else []))
        | set(str(code) for code in (timeline.safe_issue_codes if timeline else []))
        | set(run.gate2_handoff.safe_issue_codes if run.gate2_handoff is not None else [])
        | {
            window.failure_category
            for window in windows
            if isinstance(window.failure_category, str) and window.failure_category
        }
        | {
            code
            for window in windows
            for code in (
                window.provider_error_diagnostics.get("schema_error_rule_codes", [])
                if isinstance(window.provider_error_diagnostics, dict)
                else []
            )
            if isinstance(code, str)
        }
    )
    return {
        "analysis_run_id": run.analysis_run_id,
        "project_id": run.project_id,
        "document_id": run.document_id,
        "pipeline_phase": str(run.pipeline_phase),
        "pipeline_safe_issue_codes": list(run.pipeline_safe_issue_codes),
        "gate1": str(gate1.decision) if gate1 is not None else "PENDING",
        "narrative": str(run.status),
        "narrative_failure_summary": _narrative_failure_summary(windows),
        "batch_summary": _batch_summary(run, windows),
        "window_summary": _window_summary(windows),
        "structured_execution": _structured_execution_summary(windows),
        "provider_health": provider_health.model_dump(mode="json"),
        "gate2": _gate2_status(run, aggregate, latest_gate2_route),
        "gate2_handoff": (
            run.gate2_handoff.model_dump(mode="json") if run.gate2_handoff is not None else None
        ),
        "narrative_recovery": _recovery_status(attempts),
        "timeline": str(timeline.status) if timeline is not None else "NOT_READY",
        "timeline_failure_category": (
            str(timeline.failure_category)
            if timeline is not None and timeline.failure_category is not None
            else None
        ),
        "timeline_safe_issue_codes": (
            list(timeline.safe_issue_codes) if timeline is not None else []
        ),
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


def _latest_approved_recovery_route(attempts: list[Any]) -> Any | None:
    """Return the newest fresh APPROVED route eligible for downstream execution."""

    for attempt in reversed(attempts):
        route = getattr(attempt, "fresh_route", None)
        if (
            route is not None
            and str(getattr(route, "decision", "")) == "APPROVED"
            and getattr(route, "approved_proposal_bundle", None) is not None
        ):
            return route
    return None


def _gate2_safe_issue_codes(result: Any) -> set[str]:
    """Return only typed Gate 2 diagnostics suitable for the progress summary."""

    if result is None:
        return set()
    return {
        str(issue.code)
        for issue in [
            *getattr(result, "execution_issues", []),
            *(issue for decision in getattr(result, "decisions", []) for issue in decision.issues),
        ]
        if isinstance(getattr(issue, "code", None), str)
    }


def _ensure_project(repository: SourceRepository, project_id: str, name: str | None) -> None:
    if repository.get_project(project_id) is not None:
        return
    display_name = (
        name.strip() if isinstance(name, str) and name.strip() else f"Local demo {project_id}"
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
    app_state: State,
    circuit_repository: ProviderCircuitRepository,
) -> None:
    """Validate real-provider readiness inside the background execution boundary."""

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
    provider = getattr(app_state, "narrative_analyst_provider", None)
    if provider is None:
        provider = build_openai_compatible_provider(settings)
        # Reuse the exact instance that was preflighted.  Constructing a second
        # provider inside the Narrative workflow loses the negotiated capability
        # profile and silently falls back to legacy prompt-only requests.
        app_state.narrative_analyst_provider = provider
    result = ProviderHealthService(settings=settings, repository=circuit_repository).preflight(
        provider_key=settings.llm_provider_name,
        provider=provider,
    )
    if str(result.status) != "AVAILABLE":
        raise HTTPException(status_code=409, detail=result.model_dump(mode="json"))
    capability_service = ProviderCapabilityService(
        settings=settings, repository=circuit_repository
    )
    capability = capability_service.resolve(
        provider_key=f"{settings.llm_provider_name}:{settings.llm_model}",
        provider=provider,
    )
    if capability.selected_output_mode == StructuredOutputMode.UNAVAILABLE:
        raise HTTPException(
            status_code=409,
            detail={
                "safe_issue_codes": capability.safe_issue_codes,
                "structured_output": "UNAVAILABLE",
            },
        )
    unsupported_schema_modes = [
        item.output_schema_name
        for item in capability.schema_capabilities
        if item.selected_output_mode
        in {StructuredOutputMode.UNAVAILABLE, StructuredOutputMode.PROMPT_ONLY}
    ]
    if unsupported_schema_modes:
        raise HTTPException(
            status_code=409,
            detail={
                "safe_issue_codes": ["NARRATIVE_SCHEMA_CAPABILITY_UNAVAILABLE"],
                "unsupported_schema_count": len(unsupported_schema_modes),
            },
        )


def _safe_preflight_issue_codes(exc: HTTPException) -> list[str]:
    """Extract only allowlisted issue identifiers from a preflight failure."""

    detail = exc.detail
    if isinstance(detail, dict):
        values = detail.get("safe_issue_codes", [])
        if isinstance(values, list):
            return sorted({str(value) for value in values if isinstance(value, str)})
    if isinstance(detail, str):
        if "API key" in detail:
            return ["PROVIDER_API_KEY_MISSING"]
        if "Fake" in detail or "ENABLE_REAL_LLM" in detail:
            return ["REAL_LLM_NOT_ENABLED"]
    return ["PROVIDER_PREFLIGHT_FAILED"]


def _preflight_retry_at(exc: HTTPException) -> datetime | None:
    """Return the persisted retry deadline for a transient Provider preflight failure."""

    detail = exc.detail
    if not isinstance(detail, dict) or detail.get("status") != "WAITING_RETRY":
        return None
    raw_retry_at = detail.get("next_eligible_retry_at")
    if not isinstance(raw_retry_at, str):
        return None
    try:
        retry_at = datetime.fromisoformat(raw_retry_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return retry_at if retry_at.tzinfo is not None else retry_at.replace(tzinfo=UTC)


def _preflight_requires_human_action(exc: HTTPException) -> bool:
    """A paused circuit has consumed its bounded preflight retry allowance."""

    detail = exc.detail
    return isinstance(detail, dict) and detail.get("status") == "PAUSED"


def _save_pipeline_failure(
    session_factory: Any,
    analysis_run_id: str,
    issue_codes: list[str],
) -> None:
    """Persist a source-free terminal startup failure after the request returned."""

    session = session_factory()
    try:
        repository = NarrativeAnalysisRepository(session)
        run = repository.get_run(analysis_run_id)
        if run is None:
            return
        # A downstream orchestration failure cannot invalidate a fully saved
        # Narrative result.  Retaining SUCCEEDED keeps Gate 2 resumable while
        # the separate pipeline phase exposes the safe worker diagnostic.
        status = (
            NarrativeAnalysisRunStatus.SUCCEEDED
            if run.status == NarrativeAnalysisRunStatus.SUCCEEDED
            else NarrativeAnalysisRunStatus.FAILED
        )
        repository.save_run(
            run.model_copy(
                update={
                    "status": status,
                    "pipeline_phase": NarrativePipelinePhase.FAILED,
                    "pipeline_safe_issue_codes": sorted(set(issue_codes)),
                }
            )
        )
    finally:
        session.close()


def _run_pipeline_background(
    session_factory: Any,
    app_state: State,
    analysis_run_id: str,
    real_llm_requested: bool,
) -> None:
    """Run preflight and the existing worker after the run id has been returned."""

    while True:
        retry_at: datetime | None = None
        start_worker = True
        session = session_factory()
        try:
            analysis_repository = NarrativeAnalysisRepository(session)
            run = analysis_repository.get_run(analysis_run_id)
            if run is None:
                return
            analysis_repository.save_run(
                run.model_copy(
                    update={
                        "pipeline_phase": (
                            NarrativePipelinePhase.PROVIDER_CHECKING
                            if real_llm_requested
                            else NarrativePipelinePhase.NARRATIVE_RUNNING
                        )
                    }
                )
            )
            if real_llm_requested:
                try:
                    _require_real_pipeline_opt_in(
                        True,
                        app_state=app_state,
                        circuit_repository=ProviderCircuitRepository(session),
                    )
                except HTTPException as exc:
                    issue_codes = _safe_preflight_issue_codes(exc)
                    retry_at = _preflight_retry_at(exc)
                    run = analysis_repository.get_run(analysis_run_id)
                    if run is not None and retry_at is not None:
                        analysis_repository.save_run(
                            run.model_copy(
                                update={
                                    "status": NarrativeAnalysisRunStatus.RUNNING,
                                    "pipeline_phase": NarrativePipelinePhase.PROVIDER_CHECKING,
                                    "pipeline_safe_issue_codes": issue_codes,
                                }
                            )
                        )
                    elif run is not None:
                        needs_human_action = _preflight_requires_human_action(exc)
                        analysis_repository.save_run(
                            run.model_copy(
                                update={
                                    "status": (
                                        NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION
                                        if needs_human_action
                                        else NarrativeAnalysisRunStatus.FAILED
                                    ),
                                    "pipeline_phase": (
                                        NarrativePipelinePhase.NEEDS_HUMAN_ACTION
                                        if needs_human_action
                                        else NarrativePipelinePhase.FAILED
                                    ),
                                    "pipeline_safe_issue_codes": issue_codes,
                                }
                            )
                        )
                    start_worker = False
                except Exception:
                    run = analysis_repository.get_run(analysis_run_id)
                    if run is not None:
                        analysis_repository.save_run(
                            run.model_copy(
                                update={
                                    "status": NarrativeAnalysisRunStatus.FAILED,
                                    "pipeline_phase": NarrativePipelinePhase.FAILED,
                                    "pipeline_safe_issue_codes": ["PROVIDER_PREFLIGHT_FAILED"],
                                }
                            )
                        )
                    start_worker = False
        finally:
            session.close()

        if retry_at is not None:
            delay = _pipeline_retry_wait_seconds(retry_at)
            if delay > 0:
                sleep(delay)
            continue
        if not start_worker:
            return
        break

    _run_pipeline_until_terminal(
        session_factory,
        app_state,
        analysis_run_id,
        real_llm_requested,
    )


def _pipeline_retry_wait_seconds(
    next_retry_at: datetime | None,
    *,
    now: datetime | None = None,
) -> float:
    """Return a bounded wait; an overdue checkpoint must be runnable immediately."""

    if next_retry_at is None:
        return 1.0
    current = now or datetime.now(UTC)
    return max(0.0, min(5.0, (next_retry_at - current).total_seconds()))


def _run_pipeline_until_terminal(
    session_factory: Any,
    app_state: State,
    analysis_run_id: str,
    real_llm_requested: bool,
) -> None:
    """Keep the background task alive across persisted window retry deadlines.

    The worker intentionally returns RUNNING while a failed window is waiting for
    backoff.  The old one-shot caller then exited permanently, leaving the run in
    RUNNING forever.  Re-entering the idempotent worker after the deadline resumes
    only eligible windows; successful windows remain untouched.
    """

    while True:
        try:
            _run_whole_document_analysis(
                session_factory,
                app_state,
                analysis_run_id,
                real_llm_requested,
            )
        except Exception:
            _save_pipeline_failure(session_factory, analysis_run_id, ["PIPELINE_WORKER_FAILED"])
            return

        session = session_factory()
        try:
            repository = NarrativeAnalysisRepository(session)
            run = repository.get_run(analysis_run_id)
            if run is None:
                return
            if run.status != NarrativeAnalysisRunStatus.RUNNING:
                phase = (
                    NarrativePipelinePhase.COMPLETED
                    if run.status == NarrativeAnalysisRunStatus.SUCCEEDED
                    else NarrativePipelinePhase.NEEDS_HUMAN_ACTION
                    if run.status == NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION
                    else NarrativePipelinePhase.FAILED
                )
                update: dict[str, object] = {"pipeline_phase": phase}
                if run.status == NarrativeAnalysisRunStatus.SUCCEEDED:
                    # The durable circuit audit retains transient Provider failures;
                    # the completed run should not continue to present them as current.
                    update["pipeline_safe_issue_codes"] = []
                repository.save_run(run.model_copy(update=update))
                return
            retry_times = [
                window.next_eligible_retry_at
                for window in repository.list_windows(analysis_run_id)
                if window.next_eligible_retry_at is not None
            ]
            next_retry_at = min(retry_times) if retry_times else None
        finally:
            session.close()

        delay = _pipeline_retry_wait_seconds(next_retry_at)
        if delay > 0:
            sleep(delay)


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
        if str(window.status) in {"FAILED", "EXHAUSTED", "NEEDS_HUMAN_ACTION"}
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
    output_token_budgets: set[int] = set()
    recovery_phase_counts: dict[str, int] = {}
    deferred_window_count = 0
    overdue_retry_count = 0
    now = datetime.now(UTC)
    for window in windows:
        status = str(window.status)
        counts[status] = counts.get(status, 0) + 1
        phase = str(window.recovery_phase)
        recovery_phase_counts[phase] = recovery_phase_counts.get(phase, 0) + 1
        attempts_used += int(window.attempt_count)
        provider_requests_used += int(window.provider_request_count)
        elapsed_seconds_used += int(window.elapsed_seconds_used)
        output_tokens_used += int(window.output_tokens_used)
        output_token_budgets.add(int(window.output_token_budget))
        if window.next_eligible_retry_at is not None:
            retry_times.append(window.next_eligible_retry_at)
            if window.next_eligible_retry_at > now:
                deferred_window_count += 1
            else:
                overdue_retry_count += 1
    return {
        "total": len(windows),
        "status_counts": counts,
        "attempts_used": attempts_used,
        "provider_requests_used": provider_requests_used,
        "elapsed_seconds_used": elapsed_seconds_used,
        "output_tokens_used": output_tokens_used,
        "output_token_budgets": sorted(output_token_budgets),
        "next_eligible_retry_at": min(retry_times).isoformat() if retry_times else None,
        "recovery_phase_counts": recovery_phase_counts,
        "deferred_window_count": deferred_window_count,
        "overdue_retry_count": overdue_retry_count,
        "automatic_split_count": counts.get("SPLIT", 0),
    }


def _structured_execution_summary(windows: list[Any]) -> dict[str, object]:
    """Return only persisted, allowlisted structured Provider execution state."""

    completion_values = [
        window.provider_completion_tokens
        for window in windows
        if isinstance(window.provider_completion_tokens, int)
    ]
    return {
        "selected_output_modes": sorted(
            {
                str(window.selected_output_mode)
                for window in windows
                if window.selected_output_mode is not None
            }
        ),
        "capability_states": sorted(
            {
                str(window.capability_state)
                for window in windows
                if window.capability_state is not None
            }
        ),
        "schema_recovery_attempt_count": sum(
            window.schema_recovery_attempt_count for window in windows
        ),
        "recovery_phases": sorted({str(window.recovery_phase) for window in windows}),
        "terminal_reasons": sorted(
            {
                str(window.terminal_reason)
                for window in windows
                if window.terminal_reason is not None
            }
        ),
        "length_recovery_attempts_used": sum(
            window.length_recovery_attempts_used for window in windows
        ),
        "schema_repair_attempts_used": sum(
            window.schema_repair_attempts_used for window in windows
        ),
        "max_split_depth": max((window.split_depth for window in windows), default=0),
        "completion_tokens": sum(completion_values) if completion_values else None,
        "completion_tokens_status": (
            "REPORTED" if completion_values else "PROVIDER_NOT_REPORTED"
        ),
        "provider_calls_consumed": sum(window.provider_request_count for window in windows),
        "provider_calls_budget": sum(window.max_call_attempts for window in windows),
        "elapsed_seconds_consumed": sum(window.elapsed_seconds_used for window in windows),
        "elapsed_seconds_budget": sum(window.time_budget_seconds for window in windows),
        "needs_human_action": any(
            str(window.status) == "NEEDS_HUMAN_ACTION" for window in windows
        ),
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
        elif all(status in {"SUCCEEDED", "SPLIT"} for status in statuses) and any(
            status == "SUCCEEDED" for status in statuses
        ):
            # A split parent remains as an audit checkpoint after every child
            # has succeeded.  It must not make the completed batch look planned.
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
