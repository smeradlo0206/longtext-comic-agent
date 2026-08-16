"""Context assembly placeholder used by agents instead of direct database access."""

from collections.abc import Iterable
from dataclasses import dataclass

from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    StoryBibleContextV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)

MAX_STORYBIBLE_CONTEXT_ITEMS = 3
MAX_STORYBIBLE_CONTEXT_PROPOSALS = 20
MAX_STORYBIBLE_CONTEXT_TEMPORAL_RELATIONS = 64
MAX_STORYBIBLE_SOURCE_CHUNKS = 3


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

    def storybible_context(
        self,
        *,
        project_id: str,
        profile_ids: Iterable[str],
        source_chunks: Iterable[SourceChunkV1],
        repository: StoryBibleRepository,
        entity_proposals: Iterable[EntityProposalV1] = (),
        event_proposals: Iterable[EventProposalV1] = (),
        state_change_proposals: Iterable[StateChangeProposalV1] = (),
        temporal_relation_proposals: Iterable[TemporalRelationProposalV1] = (),
        world_rules: Iterable[WorldRuleV1] = (),
    ) -> StoryBibleContextV1:
        """Build project-scoped context around caller-selected profiles and chunks."""

        profiles = []
        states: list[StoryEntityStateV1] = []
        relationships: list[StoryRelationshipV1] = []
        seen_profiles: set[str] = set()
        seen_resources: set[tuple[str, str]] = set()

        for profile_id in profile_ids:
            if profile_id in seen_profiles:
                continue
            seen_profiles.add(profile_id)
            profile = repository.get_profile(project_id, profile_id)
            if profile is None:
                continue
            profiles.append(profile)
            for resource in repository.list_related_resources(project_id, profile_id)[:3]:
                if isinstance(resource, StoryEntityStateV1):
                    key = ("state", resource.state_id)
                    if (
                        key not in seen_resources
                        and len(states) < MAX_STORYBIBLE_CONTEXT_ITEMS
                    ):
                        seen_resources.add(key)
                        states.append(resource)
                else:
                    key = ("relationship", resource.relationship_id)
                    if (
                        key not in seen_resources
                        and len(relationships) < MAX_STORYBIBLE_CONTEXT_ITEMS
                    ):
                        seen_resources.add(key)
                        relationships.append(resource)
            if len(profiles) == MAX_STORYBIBLE_CONTEXT_ITEMS:
                break

        candidate_chunks = list(source_chunks)
        if any(source_chunk.project_id != project_id for source_chunk in candidate_chunks):
            raise ValueError("source chunk and context must belong to the same project")

        selected_chunk_ids: list[str] = []
        for source_chunk in candidate_chunks:
            if source_chunk.chunk_id not in selected_chunk_ids:
                selected_chunk_ids.append(source_chunk.chunk_id)
            if len(selected_chunk_ids) == MAX_STORYBIBLE_SOURCE_CHUNKS:
                break

        selected_world_rules = list(world_rules)
        if any(rule.project_id != project_id for rule in selected_world_rules):
            raise ValueError("world rule and context must belong to the same project")

        return StoryBibleContextV1(
            project_id=project_id,
            entity_proposals=list(entity_proposals)[:MAX_STORYBIBLE_CONTEXT_PROPOSALS],
            event_proposals=list(event_proposals)[:MAX_STORYBIBLE_CONTEXT_PROPOSALS],
            state_change_proposals=list(state_change_proposals)[
                :MAX_STORYBIBLE_CONTEXT_PROPOSALS
            ],
            temporal_relation_proposals=list(temporal_relation_proposals)[
                :MAX_STORYBIBLE_CONTEXT_TEMPORAL_RELATIONS
            ],
            profiles=profiles,
            states=states,
            relationships=relationships,
            world_rules=selected_world_rules[:MAX_STORYBIBLE_CONTEXT_ITEMS],
            source_chunk_ids=selected_chunk_ids,
        )
