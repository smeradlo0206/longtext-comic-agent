"""Server-only adaptation from trusted production context to Curator inputs."""

from dataclasses import dataclass

from comic_agent.schemas.storybible import (
    StoryBibleContextV1,
    StoryBibleCuratorContextLineageV1,
    StoryBibleProductionContextV1,
)


class StoryBibleContextBudgetExceededError(ValueError):
    """The trusted context cannot fit the current single Curator call."""


class StoryBibleContextLineageError(ValueError):
    """The Curator context is missing or inconsistent server-owned lineage."""


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
        lineage: StoryBibleCuratorContextLineageV1 | None = None,
        require_lineage: bool = False,
    ) -> StoryBibleCuratorInput:
        if len(production.source_chunks) > max_context_chunks:
            raise StoryBibleContextBudgetExceededError(
                "trusted StoryBible context exceeds the single-call chunk budget"
            )
        if require_lineage and lineage is None:
            raise StoryBibleContextLineageError(
                "Curator context requires server-owned production lineage"
            )
        if lineage is not None:
            self._validate_lineage(production, lineage)
        chunk_texts = {chunk.chunk_id: chunk.text for chunk in production.source_chunks}
        return StoryBibleCuratorInput(
            context=StoryBibleContextV1(
                schema_version="1.1",
                project_id=production.project_id,
                lineage=lineage,
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

    def adapt_with_lineage(
        self,
        production: StoryBibleProductionContextV1,
        *,
        lineage: StoryBibleCuratorContextLineageV1 | None,
        max_context_chunks: int = 3,
    ) -> StoryBibleCuratorInput:
        """Build a strict production Curator context with required lineage."""

        return self.adapt(
            production,
            max_context_chunks=max_context_chunks,
            lineage=lineage,
            require_lineage=True,
        )

    @staticmethod
    def _validate_lineage(
        production: StoryBibleProductionContextV1,
        lineage: StoryBibleCuratorContextLineageV1,
    ) -> None:
        expected = {
            "dossier_id": production.production_dossier_id,
            "human_review_id": production.human_review_id,
            "approved_timeline_bundle_id": production.approved_timeline_bundle_id,
            "canonical_snapshot_hash": production.canonical_storybible_snapshot_hash,
        }
        for field, value in expected.items():
            if value != getattr(lineage, field):
                raise StoryBibleContextLineageError(
                    f"Curator lineage field does not match production context: {field}"
                )
        if not lineage.canonical_snapshot_identity.strip():
            raise StoryBibleContextLineageError(
                "Curator lineage canonical snapshot identity cannot be blank"
            )
