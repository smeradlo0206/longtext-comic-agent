"""Server-only adaptation from trusted production context to Curator inputs."""

from dataclasses import dataclass

from comic_agent.schemas.storybible import StoryBibleContextV1, StoryBibleProductionContextV1


class StoryBibleContextBudgetExceededError(ValueError):
    """The trusted context cannot fit the current single Curator call."""


@dataclass(frozen=True)
class StoryBibleCuratorInput:
    """Legacy Curator context plus its trusted source text."""

    context: StoryBibleContextV1
    chunk_texts: dict[str, str]


class StoryBibleCuratorInputAdapter:
    """Map trusted production material without caller-controlled derived inputs."""

    def adapt(
        self,
        production: StoryBibleProductionContextV1,
        *,
        max_context_chunks: int = 3,
    ) -> StoryBibleCuratorInput:
        if len(production.source_chunks) > max_context_chunks:
            raise StoryBibleContextBudgetExceededError(
                "trusted StoryBible context exceeds the single-call chunk budget"
            )
        chunk_texts = {chunk.chunk_id: chunk.text for chunk in production.source_chunks}
        return StoryBibleCuratorInput(
            context=StoryBibleContextV1(
                project_id=production.project_id,
                entity_proposals=production.approved_entities,
                event_proposals=production.approved_events,
                state_change_proposals=production.approved_state_changes,
                temporal_relation_proposals=production.approved_temporal_relations,
                profiles=production.canonical_snapshot.profiles,
                states=production.canonical_snapshot.states,
                relationships=production.canonical_snapshot.relationships,
                world_rules=production.canonical_snapshot.world_rules,
                source_chunk_ids=production.source_chunk_ids,
            ),
            chunk_texts=chunk_texts,
        )
