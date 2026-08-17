"""Convert one persisted Narrative Analyst batch into owned proposal sources."""

from collections.abc import Sequence

from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalBatchV1,
    ClaimProposalV1,
    EntityProposalBatchV1,
    EntityProposalV1,
    EventProposalBatchV1,
    EventProposalV1,
    KnowledgeStateProposalBatchV1,
    KnowledgeStateProposalV1,
    RelationshipSignalProposalBatchV1,
    RelationshipSignalProposalV1,
    StateChangeProposalBatchV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.workflow import (
    AgentRunV1,
    NarrativeAnalysisProposalSourceV1,
    NarrativeAnalysisWindowV1,
)


def proposal_sources_for_window(
    agent_run: AgentRunV1,
    window: NarrativeAnalysisWindowV1,
) -> list[NarrativeAnalysisProposalSourceV1]:
    """Return only the proposals owned by one persisted window."""

    payload = agent_run.payload.get("proposal")
    if not isinstance(payload, dict):
        return []

    proposals: Sequence[
        EventProposalV1
        | EntityProposalV1
        | ClaimProposalV1
        | KnowledgeStateProposalV1
        | StateChangeProposalV1
        | RelationshipSignalProposalV1
        | CampusContentProfileProposalV1
    ]
    if agent_run.output_schema == "EventProposalBatchV1":
        proposals = tuple(EventProposalBatchV1.model_validate(payload).events)
    elif agent_run.output_schema == "EntityProposalBatchV1":
        proposals = tuple(EntityProposalBatchV1.model_validate(payload).entities)
    elif agent_run.output_schema == "ClaimProposalBatchV1":
        proposals = tuple(ClaimProposalBatchV1.model_validate(payload).claims)
    elif agent_run.output_schema == "KnowledgeStateProposalBatchV1":
        proposals = tuple(KnowledgeStateProposalBatchV1.model_validate(payload).states)
    elif agent_run.output_schema == "StateChangeProposalBatchV1":
        proposals = tuple(
            proposal
            for proposal in StateChangeProposalBatchV1.model_validate(payload).changes
            if _state_change_proposal_is_owned(window, proposal)
        )
    elif agent_run.output_schema == "RelationshipSignalProposalBatchV1":
        proposals = tuple(
            proposal
            for proposal in RelationshipSignalProposalBatchV1.model_validate(payload).signals
            if _relationship_signal_is_owned(window, proposal)
        )
    elif agent_run.output_schema == "CampusContentProfileProposalV1":
        proposals = (CampusContentProfileProposalV1.model_validate(payload),)
    else:
        return []

    return [
        NarrativeAnalysisProposalSourceV1(
            mode=window.mode,
            agent_run_id=agent_run.agent_run_id,
            proposal=proposal,
        )
        for proposal in proposals
    ]


def _state_change_proposal_is_owned(
    window: NarrativeAnalysisWindowV1,
    proposal: StateChangeProposalV1,
) -> bool:
    """Use the first new-value EvidenceRef as the deterministic output owner."""

    if not proposal.new_value_evidence_indexes:
        return False
    evidence_index = proposal.new_value_evidence_indexes[0]
    if evidence_index >= len(proposal.evidence_refs):
        return False
    return proposal.evidence_refs[evidence_index].chunk_id in set(window.owned_chunk_ids)


def _relationship_signal_is_owned(
    window: NarrativeAnalysisWindowV1,
    proposal: RelationshipSignalProposalV1,
) -> bool:
    """Use the first relationship EvidenceRef as its deterministic leaf owner."""

    return bool(proposal.evidence_refs) and (
        proposal.evidence_refs[0].chunk_id in set(window.owned_chunk_ids)
    )
