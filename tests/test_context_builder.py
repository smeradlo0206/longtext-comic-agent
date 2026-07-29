from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.document_parser import DocumentParser


def _repository(tmp_path: Path) -> SourceRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'context.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    return SourceRepository(session)


def _import_text(
    repository: SourceRepository,
    project_id: str,
    filename: str,
    text: str,
):
    parsed = DocumentParser().parse_txt(
        project_id=project_id,
        filename=filename,
        text=text,
    )
    repository.import_parsed_document(parsed)
    return parsed


def test_context_builder_builds_context_from_project_chunks(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    parsed = _import_text(
        repository,
        "project-1",
        "source.txt",
        "第一章 开端\n\n甲走进教室。\n\n乙递给甲一张纸条。",
    )

    context = ContextBuilder(repository).build_from_chunk_ids(
        project_id="project-1",
        chunk_ids=[parsed.chunks[1].chunk_id, parsed.chunks[0].chunk_id],
    )

    assert context.project_id == "project-1"
    assert context.source_chunk_ids == [parsed.chunks[1].chunk_id, parsed.chunks[0].chunk_id]
    assert [chunk.text for chunk in context.chunks] == [
        parsed.chunks[1].text,
        parsed.chunks[0].text,
    ]


def test_context_builder_rejects_missing_chunk(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="SourceChunk not found"):
        ContextBuilder(repository).build_from_chunk_ids("project-1", ["missing-chunk"])


def test_context_builder_rejects_cross_project_chunk(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    parsed = _import_text(
        repository,
        "project-2",
        "source.txt",
        "第一章 开端\n\n乙站在门口。",
    )

    with pytest.raises(ValueError, match="does not belong to project"):
        ContextBuilder(repository).build_from_chunk_ids("project-1", [parsed.chunks[0].chunk_id])


def test_context_builder_rejects_too_many_chunks(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="at most 1 chunks"):
        ContextBuilder(repository, max_chunks=1).build_from_chunk_ids(
            "project-1",
            ["chunk-1", "chunk-2"],
        )
