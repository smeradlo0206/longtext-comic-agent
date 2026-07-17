"""Project routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from comic_agent.api.dependencies import get_repository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.source import ProjectSpecV1, SourceChapterV1

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]


@router.post("/projects", response_model=ProjectSpecV1, status_code=status.HTTP_201_CREATED)
def create_project(
    project: ProjectSpecV1,
    repository: RepositoryDep,
) -> ProjectSpecV1:
    """Create or update a project."""

    return repository.create_project(project)


@router.get("/projects/{project_id}/chapters", response_model=list[SourceChapterV1])
def list_project_chapters(
    project_id: str,
    repository: RepositoryDep,
) -> list[SourceChapterV1]:
    """List chapters for a project."""

    return repository.list_chapters(project_id)
