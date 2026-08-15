"""Project routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from comic_agent.api.dependencies import get_repository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType, SourceChapterV1

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: Annotated[dict[str, Any], Body()],
    repository: RepositoryDep,
) -> dict[str, object]:
    """Create or update a project."""

    project = _project_from_payload(payload)
    created = repository.get_project(project.id) is None
    repository.create_project(project)
    return {"project_id": project.id, "name": project.name, "created": created}


def _project_from_payload(payload: dict[str, Any]) -> ProjectSpecV1:
    project_id = str(payload.get("project_id") or payload.get("id") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    if "id" in payload and "project_type" in payload:
        return ProjectSpecV1.model_validate(payload)

    return ProjectSpecV1(
        id=project_id,
        name=name,
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


@router.get("/projects/{project_id}/chapters", response_model=list[SourceChapterV1])
def list_project_chapters(
    project_id: str,
    repository: RepositoryDep,
) -> list[SourceChapterV1]:
    """List chapters for a project."""

    return repository.list_chapters(project_id)
