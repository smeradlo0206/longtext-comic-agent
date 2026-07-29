"""Context assembly placeholder used by agents instead of direct database access."""

from dataclasses import dataclass
from typing import Protocol

from comic_agent.schemas.source import SourceChunkV1


class SourceChunkLookup(Protocol):
    """Repository capability needed by ContextBuilder."""

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        """Return a source chunk by id."""


@dataclass(frozen=True)
class AgentContext:
    """Bounded context passed into an agent."""

    project_id: str
    chunks: list[SourceChunkV1]
    source_chunk_ids: list[str]


class ContextBuilder:
    """Build bounded agent context from repository queries."""

    def __init__(self, source_repository: SourceChunkLookup, max_chunks: int = 8) -> None:
        self._source_repository = source_repository
        self._max_chunks = max_chunks

    def build_from_chunk_ids(self, project_id: str, chunk_ids: list[str]) -> AgentContext:
        """Create bounded context from explicit SourceChunk ids."""

        if len(chunk_ids) > self._max_chunks:
            raise ValueError(f"ContextBuilder accepts at most {self._max_chunks} chunks")

        chunks: list[SourceChunkV1] = []
        for chunk_id in chunk_ids:
            chunk = self._source_repository.get_chunk(chunk_id)
            if chunk is None:
                raise ValueError(f"SourceChunk not found: {chunk_id}")
            if chunk.project_id != project_id:
                raise ValueError(f"SourceChunk {chunk_id} does not belong to project {project_id}")
            chunks.append(chunk)

        return AgentContext(project_id=project_id, chunks=chunks, source_chunk_ids=chunk_ids)

    def from_chunks(self, project_id: str, chunks: list[SourceChunkV1]) -> AgentContext:
        """Create a deterministic context object."""

        return AgentContext(
            project_id=project_id,
            chunks=chunks,
            source_chunk_ids=[chunk.chunk_id for chunk in chunks],
        )
