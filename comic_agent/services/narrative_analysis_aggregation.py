"""Typed, conservative aggregation for whole-document proposal candidates."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    KnowledgeTemporalAnchorV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.workflow import (
    AggregatedClaimProposalV1,
    AggregatedEntityProposalV1,
    AggregatedEventProposalV1,
    AggregatedKnowledgeStateProposalV1,
    AggregatedStateChangeProposalV1,
    NarrativeAnalysisProposalSourceV1,
    NarrativeAnalysisResultV1,
)


def aggregate_narrative_analysis(
    sources: list[NarrativeAnalysisProposalSourceV1],
    *,
    analysis_run_id: str = "aggregate-preview",
) -> NarrativeAnalysisResultV1:
    """Merge only exact documented keys; preserve all source run and evidence references."""

    events: dict[tuple[object, ...], AggregatedEventProposalV1] = {}
    entities: dict[tuple[object, ...], AggregatedEntityProposalV1] = {}
    claims: dict[tuple[object, ...], AggregatedClaimProposalV1] = {}
    knowledge_states: dict[tuple[object, ...], AggregatedKnowledgeStateProposalV1] = {}
    state_changes: dict[tuple[object, ...], AggregatedStateChangeProposalV1] = {}
    for source in sources:
        proposal = source.proposal
        if isinstance(proposal, EventProposalV1):
            event_key = (
                _normalized(proposal.event_type),
                _normalized(proposal.summary),
                _evidence_key(proposal.evidence_refs),
            )
            existing_event = events.get(event_key)
            if existing_event is None:
                events[event_key] = AggregatedEventProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                events[event_key] = existing_event.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_event.agent_run_ids, source.agent_run_id
                        )
                    }
                )
        elif isinstance(proposal, EntityProposalV1):
            entity_key = (
                _normalized(proposal.canonical_name),
                _normalized(str(proposal.entity_type)),
            )
            existing_entity = entities.get(entity_key)
            if existing_entity is None:
                entities[entity_key] = AggregatedEntityProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                entities[entity_key] = existing_entity.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_entity.agent_run_ids, source.agent_run_id
                        ),
                        "evidence_refs": _merge_evidence(
                            existing_entity.evidence_refs, proposal.evidence_refs
                        ),
                    }
                )
        elif isinstance(proposal, ClaimProposalV1):
            claim_key = (
                _normalized(str(proposal.claim_type)),
                _normalized(proposal.claim_text),
                _normalized(str(proposal.source_type)),
                _evidence_key(proposal.evidence_refs),
            )
            existing_claim = claims.get(claim_key)
            if existing_claim is None:
                claims[claim_key] = AggregatedClaimProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                claims[claim_key] = existing_claim.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_claim.agent_run_ids, source.agent_run_id
                        )
                    }
                )
        elif isinstance(proposal, KnowledgeStateProposalV1):
            knowledge_key = _knowledge_state_key(proposal)
            existing_state = knowledge_states.get(knowledge_key)
            if existing_state is None:
                knowledge_states[knowledge_key] = AggregatedKnowledgeStateProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                knowledge_states[knowledge_key] = existing_state.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_state.agent_run_ids, source.agent_run_id
                        ),
                        "evidence_refs": _merge_evidence(
                            existing_state.evidence_refs, proposal.evidence_refs
                        ),
                    }
                )
        elif isinstance(proposal, StateChangeProposalV1):
            state_change_key = _state_change_key(proposal)
            existing_change = state_changes.get(state_change_key)
            if existing_change is None:
                state_changes[state_change_key] = AggregatedStateChangeProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                state_changes[state_change_key] = existing_change.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_change.agent_run_ids, source.agent_run_id
                        ),
                        "evidence_refs": _merge_evidence(
                            existing_change.evidence_refs, proposal.evidence_refs
                        ),
                    }
                )
    return NarrativeAnalysisResultV1(
        analysis_run_id=analysis_run_id,
        events=list(events.values()),
        entities=list(entities.values()),
        claims=list(claims.values()),
        knowledge_states=list(knowledge_states.values()),
        state_changes=list(state_changes.values()),
    )


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _evidence_key(evidence_refs: list[EvidenceRefV1]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (reference.chunk_id, reference.quote_start, reference.quote_end, reference.quote_text)
        for reference in evidence_refs
    )


def _append_unique(values: list[str], value: str) -> list[str]:
    return values if value in values else [*values, value]


def _merge_evidence(
    existing: list[EvidenceRefV1], additions: list[EvidenceRefV1]
) -> list[EvidenceRefV1]:
    merged = list(existing)
    existing_keys = set(_evidence_key(existing))
    for evidence in additions:
        key = _evidence_key([evidence])[0]
        if key not in existing_keys:
            merged.append(evidence)
            existing_keys.add(key)
    return merged


def _knowledge_state_key(proposal: KnowledgeStateProposalV1) -> tuple[object, ...]:
    """Preserve resolution state; aggregation never links or upgrades references."""

    if proposal.schema_version != "1.1" or proposal.subject is None or proposal.target is None:
        return ("legacy", proposal.proposal_id)
    subject = proposal.subject
    target = proposal.target
    return (
        subject.resolution_status,
        subject.entity_proposal_id,
        _normalized(subject.mention_text),
        target.resolution_status,
        target.target_kind,
        target.proposal_id,
        target.proposal_schema,
        _normalized(target.target_text),
        proposal.epistemic_status,
        proposal.epistemic_basis,
        proposal.reality_layer,
        _temporal_anchor_key(proposal.valid_from),
        _temporal_anchor_key(proposal.valid_until),
    )


def _temporal_anchor_key(anchor: KnowledgeTemporalAnchorV1 | None) -> tuple[object, ...] | None:
    if anchor is None:
        return None
    resolution_status = anchor.resolution_status
    event_proposal_id = anchor.event_proposal_id
    anchor_text = anchor.anchor_text
    return (
        resolution_status,
        event_proposal_id,
        _normalized(anchor_text or ""),
    )


def _state_change_key(proposal: StateChangeProposalV1) -> tuple[object, ...]:
    """Return the v1.2/v1.3 exact semantic key without linking or normalizing candidates."""

    if (
        proposal.schema_version not in {"1.2", "1.3"}
        or proposal.event is None
        or proposal.target is None
    ):
        return ("legacy", proposal.proposal_id)
    event = proposal.event
    target = proposal.target
    return (
        event.event_summary,
        event.resolution_status,
        event.event_proposal_id,
        event.proposal_schema,
        target.mention_text,
        target.target_kind,
        target.resolution_status,
        target.entity_proposal_id,
        target.proposal_schema,
        proposal.attribute_path,
        _typed_scalar_key(proposal.old_value),
        _typed_scalar_key(proposal.new_value),
        proposal.persistent,
        proposal.reality_layer,
    )


def _typed_scalar_key(value: object) -> tuple[str, object | None]:
    """Keep JSON scalar values exact and type-sensitive for State Change aggregation."""

    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        return ("str", value)
    return (type(value).__name__, repr(value))
