"""Context assembly placeholder used by agents instead of direct database access."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.review import NarrativeAnalysisReviewRouteV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    StoryBibleCanonicalKind,
    StoryBibleContextV1,
    StoryBibleIdentityBindingV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)
from comic_agent.schemas.timeline import NarrativeTimelineReviewRouteV1
from comic_agent.services.id_service import stable_id

MAX_STORYBIBLE_CONTEXT_ITEMS = 3


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

    def __init__(
        self,
        source_repository: SourceChunkLookup | None = None,
        max_chunks: int = 8,
    ) -> None:
        self._source_repository = source_repository
        self._max_chunks = max_chunks

    def build_from_chunk_ids(self, project_id: str, chunk_ids: list[str]) -> AgentContext:
        """Create bounded context from explicit SourceChunk ids."""

        if len(chunk_ids) > self._max_chunks:
            raise ValueError(f"ContextBuilder accepts at most {self._max_chunks} chunks")
        if self._source_repository is None:
            raise ValueError("ContextBuilder requires a source repository for chunk lookup")

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
        gate2_route: NarrativeAnalysisReviewRouteV1 | None = None,
        gate3_route: NarrativeTimelineReviewRouteV1 | None = None,
    ) -> StoryBibleContextV1:
        """Build project-scoped context around caller-selected profiles and chunks."""

        if gate2_route is None or gate3_route is None:
            raise ValueError("StoryBible context requires existing Gate 2 and Gate 3 routes")

        gate2_bundle = gate2_route.approved_proposal_bundle
        gate3_bundle = gate3_route.approved_timeline_bundle
        if gate2_bundle is None or gate3_bundle is None:
            raise ValueError("StoryBible context requires approved Gate 2 and Gate 3 bundles")

        approved_proposals = [item.source.proposal for item in gate2_bundle.approved_proposals]
        entity_values = [
            proposal for proposal in approved_proposals if isinstance(proposal, EntityProposalV1)
        ][:MAX_STORYBIBLE_CONTEXT_ITEMS]
        event_values = [
            proposal for proposal in approved_proposals if isinstance(proposal, EventProposalV1)
        ][:MAX_STORYBIBLE_CONTEXT_ITEMS]
        state_change_values = [
            proposal
            for proposal in approved_proposals
            if isinstance(proposal, StateChangeProposalV1)
        ][:MAX_STORYBIBLE_CONTEXT_ITEMS]
        temporal_values = list(gate3_bundle.temporal_relations)[:MAX_STORYBIBLE_CONTEXT_ITEMS]

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
            if len(selected_chunk_ids) == 3:
                break

        selected_world_rules = list(world_rules)
        if any(rule.project_id != project_id for rule in selected_world_rules):
            raise ValueError("world rule and context must belong to the same project")

        identity_bindings = self._build_identity_bindings(
            project_id=project_id,
            entity_proposals=entity_values,
            event_proposals=event_values,
            state_change_proposals=state_change_values,
            temporal_relation_proposals=temporal_values,
            profiles=profiles,
        )

        return StoryBibleContextV1(
            project_id=project_id,
            gate2_route=gate2_route,
            gate3_route=gate3_route,
            entity_proposals=entity_values,
            event_proposals=event_values,
            state_change_proposals=state_change_values,
            temporal_relation_proposals=temporal_values,
            profiles=profiles,
            states=states,
            relationships=relationships,
            world_rules=selected_world_rules[:MAX_STORYBIBLE_CONTEXT_ITEMS],
            identity_bindings=identity_bindings,
            source_chunk_ids=selected_chunk_ids,
        )

    @staticmethod
    def _build_identity_bindings(
        *,
        project_id: str,
        entity_proposals: list[EntityProposalV1],
        event_proposals: list[EventProposalV1],
        state_change_proposals: list[StateChangeProposalV1],
        temporal_relation_proposals: list[TemporalRelationProposalV1],
        profiles: list[StoryEntityProfileV1],
    ) -> list[StoryBibleIdentityBindingV1]:
        """Assign stable project-scoped ids while retaining reviewed source ids."""

        bindings: list[StoryBibleIdentityBindingV1] = []
        existing_by_name = {
            profile.canonical_name.strip().casefold(): profile.profile_id
            for profile in profiles
        }

        def add(source_schema: str, source_id: str, kind: StoryBibleCanonicalKind) -> None:
            suffix = stable_id("storybible", project_id, kind, source_id).split("_", 1)[1]
            canonical_id = f"{project_id}:{kind.value.lower()}:{suffix}"
            bindings.append(
                StoryBibleIdentityBindingV1(
                    source_schema=source_schema,
                    source_proposal_id=source_id,
                    canonical_kind=kind,
                    canonical_id=canonical_id,
                    project_id=project_id,
                )
            )

        for entity_proposal in entity_proposals:
            canonical_id = existing_by_name.get(entity_proposal.canonical_name.strip().casefold())
            add(
                "EntityProposalV1",
                entity_proposal.proposal_id,
                StoryBibleCanonicalKind.PROFILE,
            )
            if canonical_id is not None:
                bindings[-1] = bindings[-1].model_copy(update={"canonical_id": canonical_id})
        for event_proposal in event_proposals:
            add("EventProposalV1", event_proposal.proposal_id, StoryBibleCanonicalKind.EVENT)
        for state_proposal in state_change_proposals:
            add(
                "StateChangeProposalV1",
                state_proposal.proposal_id,
                StoryBibleCanonicalKind.STATE,
            )
        for temporal_proposal in temporal_relation_proposals:
            add(
                "TemporalRelationProposalV1",
                temporal_proposal.proposal_id,
                StoryBibleCanonicalKind.RELATIONSHIP,
            )
        return bindings
