"""Long-text comic compilation, queue, and recovery endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from comic_agent.api.dependencies import (
    get_comic_production_repository,
    get_repository,
)
from comic_agent.config import get_settings
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    ComicProductionRunV1,
)
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from flux2_agent.queueing import QueueStore

router = APIRouter()

SourceRepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
ProductionRepositoryDep = Annotated[
    ComicProductionRepository,
    Depends(get_comic_production_repository),
]


def _workspace_path(path: Path) -> Path:
    settings = get_settings()
    workspace = settings.workspace_root.resolve()
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def _coordinator(
    source_repository: SourceRepository,
    production_repository: ComicProductionRepository,
) -> ComicProductionCoordinator:
    settings = get_settings()
    return ComicProductionCoordinator(
        workspace=settings.workspace_root.resolve(),
        source_repository=source_repository,
        production_repository=production_repository,
        queue_store=QueueStore(_workspace_path(settings.image_queue_root)),
    )


@router.post(
    "/projects/{project_id}/comic-runs",
    response_model=ComicProductionRunV1,
)
def create_comic_run(
    project_id: str,
    request: ComicProductionRequestV1,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
    priority: Annotated[int, Query(ge=0, le=1000)] = 100,
) -> ComicProductionRunV1:
    """Compile evidence-backed panels and enqueue one multi-page image workflow."""

    try:
        return _coordinator(source_repository, production_repository).compile_and_enqueue(
            project_id=project_id,
            request=request,
            priority=priority,
        )
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/comic-runs/{run_id}", response_model=ComicProductionRunV1)
def get_comic_run(
    run_id: str,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
) -> ComicProductionRunV1:
    """Refresh a run from durable queue state and finalize succeeded page artifacts."""

    try:
        return _coordinator(source_repository, production_repository).refresh(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/comic-runs",
    response_model=list[ComicProductionRunV1],
)
def list_comic_runs(
    project_id: str,
    production_repository: ProductionRepositoryDep,
) -> list[ComicProductionRunV1]:
    """List persisted production runs without triggering model work."""

    return production_repository.list_for_project(project_id)


@router.post("/comic-runs/{run_id}/retry", response_model=ComicProductionRunV1)
def retry_comic_run(
    run_id: str,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
) -> ComicProductionRunV1:
    """Retry a failed queue item while retaining its attempt history."""

    coordinator = _coordinator(source_repository, production_repository)
    run = production_repository.get(run_id)
    if run is None or run.queue_id is None:
        raise HTTPException(status_code=404, detail="comic production run not found")
    try:
        QueueStore(_workspace_path(get_settings().image_queue_root)).retry(run.queue_id)
        return coordinator.refresh(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/comic-runs/{run_id}/cancel", response_model=ComicProductionRunV1)
def cancel_comic_run(
    run_id: str,
    source_repository: SourceRepositoryDep,
    production_repository: ProductionRepositoryDep,
) -> ComicProductionRunV1:
    """Cancel a pending production run before GPU execution begins."""

    coordinator = _coordinator(source_repository, production_repository)
    run = production_repository.get(run_id)
    if run is None or run.queue_id is None:
        raise HTTPException(status_code=404, detail="comic production run not found")
    try:
        QueueStore(_workspace_path(get_settings().image_queue_root)).cancel(run.queue_id)
        return coordinator.refresh(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
