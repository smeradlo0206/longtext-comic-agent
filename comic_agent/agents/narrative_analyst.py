"""Narrative Analyst mode shell for proposal-only story extraction."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from comic_agent.agents.base import BaseAgent
from comic_agent.agents.claim_extraction import ClaimExtractionAgent
from comic_agent.agents.entity_extraction import EntityExtractionAgent
from comic_agent.agents.event_extraction import EventExtractionAgent
from comic_agent.agents.knowledge_state_extraction import KnowledgeStateExtractionAgent
from comic_agent.agents.relationship_signal_extraction import RelationshipSignalExtractionAgent
from comic_agent.agents.state_change_extraction import StateChangeExtractionAgent
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    EntityProposalBatchV1,
    EventProposalBatchV1,
    KnowledgeStateProposalBatchV1,
    RelationshipSignalProposalBatchV1,
    StateChangeProposalBatchV1,
)

ModeStatus = Literal["implemented", "planned", "planned_without_schema"]
Proposal = BaseModel
AgentFactory = Callable[[LLMProvider], BaseAgent[Proposal]]


@dataclass(frozen=True)
class NarrativeAnalystModeSpec:
    """Static NarrativeAnalyst mode registry entry."""

    mode: str
    description_zh: str
    status: ModeStatus
    output_schema: str | None
    schema_class: type[BaseModel] | None
    max_context_chunks: int
    requires_evidence: bool
    proposal_only: bool
    agent_factory: AgentFactory | None = None


class NarrativeAnalyst:
    """Unified entrypoint for Narrative Analyst extraction modes."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def list_modes(self) -> list[NarrativeAnalystModeSpec]:
        """Return registered Narrative Analyst modes."""

        return list(NARRATIVE_ANALYST_MODE_REGISTRY.values())

    def get_mode_spec(self, mode: str) -> NarrativeAnalystModeSpec:
        """Return one registered mode spec."""

        try:
            return NARRATIVE_ANALYST_MODE_REGISTRY[mode]
        except KeyError as exc:
            raise ValueError(f"Unsupported NarrativeAnalyst mode: {mode}") from exc

    def run(self, mode: str, input_context: dict[str, object]) -> Proposal:
        """Run an implemented mode over bounded input context."""

        mode_spec = self.get_mode_spec(mode)
        if mode_spec.status != "implemented" or mode_spec.agent_factory is None:
            raise NotImplementedError(
                f"NarrativeAnalyst mode is not implemented: {mode_spec.mode} "
                f"(status={mode_spec.status})"
            )

        agent = mode_spec.agent_factory(self._provider)
        return agent.run(input_context)


def _create_event_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return EventExtractionAgent(provider)


def _create_entity_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return EntityExtractionAgent(provider)


def _create_claim_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return ClaimExtractionAgent(provider)


def _create_knowledge_state_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return KnowledgeStateExtractionAgent(provider)


def _create_state_change_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return StateChangeExtractionAgent(provider)


def _create_relationship_signal_agent(provider: LLMProvider) -> BaseAgent[Proposal]:
    return RelationshipSignalExtractionAgent(provider)


NARRATIVE_ANALYST_MODE_REGISTRY: dict[str, NarrativeAnalystModeSpec] = {
    "event_extraction": NarrativeAnalystModeSpec(
        mode="event_extraction",
        description_zh="事件抽取",
        status="implemented",
        output_schema=EventExtractionAgent.spec.output_schema,
        schema_class=EventProposalBatchV1,
        max_context_chunks=EventExtractionAgent.spec.max_context_chunks,
        requires_evidence=EventExtractionAgent.spec.requires_evidence,
        proposal_only=not EventExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_event_agent,
    ),
    "entity_extraction": NarrativeAnalystModeSpec(
        mode="entity_extraction",
        description_zh="实体抽取",
        status="implemented",
        output_schema=EntityExtractionAgent.spec.output_schema,
        schema_class=EntityProposalBatchV1,
        max_context_chunks=EntityExtractionAgent.spec.max_context_chunks,
        requires_evidence=EntityExtractionAgent.spec.requires_evidence,
        proposal_only=not EntityExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_entity_agent,
    ),
    "claim_extraction": NarrativeAnalystModeSpec(
        mode="claim_extraction",
        description_zh="主张抽取",
        status="implemented",
        output_schema=ClaimExtractionAgent.spec.output_schema,
        schema_class=ClaimProposalBatchV1,
        max_context_chunks=ClaimExtractionAgent.spec.max_context_chunks,
        requires_evidence=ClaimExtractionAgent.spec.requires_evidence,
        proposal_only=not ClaimExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_claim_agent,
    ),
    "knowledge_state_extraction": NarrativeAnalystModeSpec(
        mode="knowledge_state_extraction",
        description_zh="知识状态抽取",
        status="implemented",
        output_schema=KnowledgeStateExtractionAgent.spec.output_schema,
        schema_class=KnowledgeStateProposalBatchV1,
        max_context_chunks=KnowledgeStateExtractionAgent.spec.max_context_chunks,
        requires_evidence=KnowledgeStateExtractionAgent.spec.requires_evidence,
        proposal_only=not KnowledgeStateExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_knowledge_state_agent,
    ),
    "state_change_extraction": NarrativeAnalystModeSpec(
        mode="state_change_extraction",
        description_zh="状态变化抽取",
        status="implemented",
        output_schema=StateChangeExtractionAgent.spec.output_schema,
        schema_class=StateChangeProposalBatchV1,
        max_context_chunks=StateChangeExtractionAgent.spec.max_context_chunks,
        requires_evidence=StateChangeExtractionAgent.spec.requires_evidence,
        proposal_only=not StateChangeExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_state_change_agent,
    ),
    "relationship_signal_extraction": NarrativeAnalystModeSpec(
        mode="relationship_signal_extraction",
        description_zh="关系信号抽取",
        status="implemented",
        output_schema=RelationshipSignalExtractionAgent.spec.output_schema,
        schema_class=RelationshipSignalProposalBatchV1,
        max_context_chunks=RelationshipSignalExtractionAgent.spec.max_context_chunks,
        requires_evidence=RelationshipSignalExtractionAgent.spec.requires_evidence,
        proposal_only=not RelationshipSignalExtractionAgent.spec.can_write_canonical_data,
        agent_factory=_create_relationship_signal_agent,
    ),
}
