"""Document import and source query routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from comic_agent.api.dependencies import get_repository
from comic_agent.config import get_settings
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.document_parser import DocumentParser

router = APIRouter()

RepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
UploadFileDep = Annotated[UploadFile, File(...)]


@router.post("/projects/{project_id}/documents/import", status_code=status.HTTP_201_CREATED)
async def import_document(
    project_id: str,
    file: UploadFileDep,
    repository: RepositoryDep,
) -> dict[str, object]:
    """Import a TXT document through multipart upload."""

    raw = await file.read()
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "source.txt"
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=415, detail="Only TXT import is implemented in phase 1")
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="TXT file must be UTF-8 encoded") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(text) > get_settings().internal_demo_max_import_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="TXT exceeds demo import character limit",
        )
    parsed = DocumentParser().parse_txt(
        project_id=project_id,
        filename=filename,
        text=text,
        mime_type=content_type,
    )
    result = repository.import_parsed_document(parsed)
    return {
        "status": result.status,
        "document": result.document.model_dump(mode="json"),
        "chapters_count": len(result.chapters),
        "chunks_count": len(result.chunks),
    }


@router.get("/chapters/{chapter_id}/chunks", response_model=list[SourceChunkV1])
def list_chapter_chunks(
    chapter_id: str,
    repository: RepositoryDep,
) -> list[SourceChunkV1]:
    """List chunks for a chapter."""

    return repository.list_chunks_for_chapter(chapter_id)


@router.get("/chunks/{chunk_id}", response_model=SourceChunkV1)
def get_chunk(
    chunk_id: str,
    repository: RepositoryDep,
) -> SourceChunkV1:
    """Return one source chunk."""

    chunk = repository.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return chunk
