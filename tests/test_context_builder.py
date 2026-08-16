"""Bounded StoryBible context construction."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EntityProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import ContextBuilder


@pytest.fixture()
def storybible_repository(tmp_path: Path) -> Iterator[StoryBibleRepository]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        yield StoryBibleRepository(session)
    finally:
        session.close()
        engine.dispose()


def chunk(chunk_id: str, project_id: str = "project-a") -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=chunk_id,
        document_id=f"document-{project_id}",
        chapter_id=f"chapter-{project_id}",
        project_id=project_id,
        order=0,
        text="source text",
        checksum=f"checksum-{chunk_id}",
    )


def entity(proposal_id: str) -> EntityProposalV1:
    return EntityProposalV1(
        proposal_id=proposal_id,
        entity_type="CHARACTER",
        canonical_name=f"Character {proposal_id}",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
        confidence=0.9,
    )


def test_proposal_lists_keep_up_to_twenty_reviewed_proposals(
    storybible_repository: StoryBibleRepository,
) -> None:
    context = ContextBuilder().storybible_context(
        project_id="project-a",
        profile_ids=[],
        source_chunks=[chunk("chunk-1")],
        repository=storybible_repository,
        entity_proposals=[entity(f"entity-{index}") for index in range(25)],
    )

    assert len(context.entity_proposals) == 20
    assert [proposal.proposal_id for proposal in context.entity_proposals] == [
        f"entity-{index}" for index in range(20)
    ]


def test_source_chunks_remain_capped_at_three(
    storybible_repository: StoryBibleRepository,
) -> None:
    context = ContextBuilder().storybible_context(
        project_id="project-a",
        profile_ids=[],
        source_chunks=[chunk(f"chunk-{index}") for index in range(6)],
        repository=storybible_repository,
    )

    assert context.source_chunk_ids == ["chunk-0", "chunk-1", "chunk-2"]


def test_context_rejects_foreign_project_source_chunks(
    storybible_repository: StoryBibleRepository,
) -> None:
    with pytest.raises(ValueError, match="same project"):
        ContextBuilder().storybible_context(
            project_id="project-a",
            profile_ids=[],
            source_chunks=[chunk("chunk-other", project_id="project-b")],
            repository=storybible_repository,
        )
