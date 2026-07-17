"""Context assembly placeholder used by agents instead of direct database access."""

from dataclasses import dataclass

from comic_agent.schemas.source import SourceChunkV1


@dataclass(frozen=True)
class AgentContext:
    """Bounded context passed into an agent."""

    project_id: str
    chunks: list[SourceChunkV1]


class ContextBuilder:
    """Build bounded agent context from repository queries."""

    def from_chunks(self, project_id: str, chunks: list[SourceChunkV1]) -> AgentContext:
        """Create a deterministic context object."""

        return AgentContext(project_id=project_id, chunks=chunks)
