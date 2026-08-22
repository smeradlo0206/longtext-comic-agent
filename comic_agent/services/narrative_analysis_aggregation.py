"""Typed, conservative aggregation for whole-document proposal candidates."""

from collections.abc import Iterable, Mapping
from typing import TypeVar

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    KnowledgeTemporalAnchorV1,
    RelationshipDirectionality,
    RelationshipParticipantRefV1,
    RelationshipSignalProposalV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.workflow import (
    AggregatedCampusContentProfileProposalV1,
    AggregatedClaimProposalV1,
    AggregatedEntityProposalV1,
    AggregatedEventProposalV1,
    AggregatedKnowledgeStateProposalV1,
    AggregatedRelationshipSignalProposalV1,
    AggregatedStateChangeProposalV1,
    NarrativeAnalysisProposalSourceV1,
    NarrativeAnalysisResultV1,
)
from comic_agent.services.narrative_proposal_id_normalizer import (
    normalize_proposal_sources,
    rewrite_proposal_ids,
)

AggregatedProposalT = TypeVar(
    "AggregatedProposalT",
    AggregatedEventProposalV1,
    AggregatedEntityProposalV1,
    AggregatedClaimProposalV1,
    AggregatedKnowledgeStateProposalV1,
    AggregatedStateChangeProposalV1,
    AggregatedRelationshipSignalProposalV1,
    AggregatedCampusContentProfileProposalV1,
)


def aggregate_narrative_analysis(
    sources: list[NarrativeAnalysisProposalSourceV1],
    *,
    analysis_run_id: str = "aggregate-preview",
    source_scopes: Mapping[str, str] | None = None,
) -> NarrativeAnalysisResultV1:
    """Merge only exact documented keys; preserve all source run and evidence references."""

    original_sources = sources
    sources = normalize_proposal_sources(
        sources, analysis_run_id=analysis_run_id, source_scopes=source_scopes
    )
    aliases: dict[tuple[str, str], str] = {}
    events: dict[tuple[object, ...], AggregatedEventProposalV1] = {}
    entities: dict[tuple[object, ...], AggregatedEntityProposalV1] = {}
    claims: dict[tuple[object, ...], AggregatedClaimProposalV1] = {}
    knowledge_states: dict[tuple[object, ...], AggregatedKnowledgeStateProposalV1] = {}
    state_changes: dict[tuple[object, ...], AggregatedStateChangeProposalV1] = {}
    relationship_signals: dict[tuple[object, ...], AggregatedRelationshipSignalProposalV1] = {}
    campus_content_profiles: dict[tuple[object, ...], AggregatedCampusContentProfileProposalV1] = {}
    for source, original_source in zip(sources, original_sources, strict=True):
        proposal = source.proposal
        semantic_proposal = original_source.proposal
        if isinstance(proposal, EventProposalV1):
            assert isinstance(semantic_proposal, EventProposalV1)
            event_key = (
                _normalized(semantic_proposal.event_type),
                _normalized(semantic_proposal.summary),
                _evidence_key(semantic_proposal.evidence_refs),
            )
            existing_event = events.get(event_key)
            if existing_event is None:
                events[event_key] = AggregatedEventProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("EventProposalV1", proposal.proposal_id)] = (
                    existing_event.proposal.proposal_id
                )
                events[event_key] = existing_event.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_event.agent_run_ids, source.agent_run_id
                        )
                    }
                )
        elif isinstance(proposal, EntityProposalV1):
            assert isinstance(semantic_proposal, EntityProposalV1)
            entity_key = (
                _normalized(semantic_proposal.canonical_name),
                _normalized(str(semantic_proposal.entity_type)),
            )
            existing_entity = entities.get(entity_key)
            if existing_entity is None:
                entities[entity_key] = AggregatedEntityProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("EntityProposalV1", proposal.proposal_id)] = (
                    existing_entity.proposal.proposal_id
                )
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
            assert isinstance(semantic_proposal, ClaimProposalV1)
            claim_key = (
                _normalized(str(semantic_proposal.claim_type)),
                _normalized(semantic_proposal.claim_text),
                _normalized(str(semantic_proposal.source_type)),
                _evidence_key(semantic_proposal.evidence_refs),
            )
            existing_claim = claims.get(claim_key)
            if existing_claim is None:
                claims[claim_key] = AggregatedClaimProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("ClaimProposalV1", proposal.proposal_id)] = (
                    existing_claim.proposal.proposal_id
                )
                claims[claim_key] = existing_claim.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_claim.agent_run_ids, source.agent_run_id
                        )
                    }
                )
        elif isinstance(proposal, KnowledgeStateProposalV1):
            assert isinstance(semantic_proposal, KnowledgeStateProposalV1)
            knowledge_key = _knowledge_state_key(semantic_proposal)
            existing_state = knowledge_states.get(knowledge_key)
            if existing_state is None:
                knowledge_states[knowledge_key] = AggregatedKnowledgeStateProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("KnowledgeStateProposalV1", proposal.proposal_id)] = (
                    existing_state.proposal.proposal_id
                )
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
            assert isinstance(semantic_proposal, StateChangeProposalV1)
            state_change_key = _state_change_key(semantic_proposal)
            existing_change = state_changes.get(state_change_key)
            if existing_change is None:
                state_changes[state_change_key] = AggregatedStateChangeProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("StateChangeProposalV1", proposal.proposal_id)] = (
                    existing_change.proposal.proposal_id
                )
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
        elif isinstance(proposal, RelationshipSignalProposalV1):
            assert isinstance(semantic_proposal, RelationshipSignalProposalV1)
            relationship_key = _relationship_signal_key(semantic_proposal)
            existing_signal = relationship_signals.get(relationship_key)
            if existing_signal is None:
                relationship_signals[relationship_key] = AggregatedRelationshipSignalProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("RelationshipSignalProposalV1", proposal.proposal_id)] = (
                    existing_signal.proposal.proposal_id
                )
                relationship_signals[relationship_key] = existing_signal.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_signal.agent_run_ids, source.agent_run_id
                        ),
                        "evidence_refs": _merge_evidence(
                            existing_signal.evidence_refs, proposal.evidence_refs
                        ),
                    }
                )
        elif isinstance(proposal, CampusContentProfileProposalV1):
            assert isinstance(semantic_proposal, CampusContentProfileProposalV1)
            profile_key = (
                semantic_proposal.project_id,
                semantic_proposal.content_type,
                tuple(semantic_proposal.audience),
                tuple(semantic_proposal.must_preserve_fact_ids),
                semantic_proposal.tone,
                semantic_proposal.page_budget,
                _evidence_key(semantic_proposal.evidence_refs),
            )
            existing_profile = campus_content_profiles.get(profile_key)
            if existing_profile is None:
                campus_content_profiles[profile_key] = AggregatedCampusContentProfileProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
                aliases[("CampusContentProfileProposalV1", proposal.proposal_id)] = (
                    existing_profile.proposal.proposal_id
                )
                campus_content_profiles[profile_key] = existing_profile.model_copy(
                    update={
                        "agent_run_ids": _append_unique(
                            existing_profile.agent_run_ids, source.agent_run_id
                        ),
                        "evidence_refs": _merge_evidence(
                            existing_profile.evidence_refs, proposal.evidence_refs
                        ),
                    }
                )
    return NarrativeAnalysisResultV1(
        analysis_run_id=analysis_run_id,
        events=_rewrite_aggregated(events.values(), aliases),
        entities=_rewrite_aggregated(entities.values(), aliases),
        claims=_rewrite_aggregated(claims.values(), aliases),
        knowledge_states=_rewrite_aggregated(knowledge_states.values(), aliases),
        state_changes=_rewrite_aggregated(state_changes.values(), aliases),
        relationship_signals=_rewrite_aggregated(relationship_signals.values(), aliases),
        campus_content_profiles=_rewrite_aggregated(campus_content_profiles.values(), aliases),
    )


def _rewrite_aggregated(  # noqa: UP047 - constrained TypeVar supports Python 3.11
    values: Iterable[AggregatedProposalT], aliases: Mapping[tuple[str, str], str]
) -> list[AggregatedProposalT]:
    def resolve(schema: str, proposal_id: str | None) -> str | None:
        while proposal_id is not None and (schema, proposal_id) in aliases:
            proposal_id = aliases[(schema, proposal_id)]
        return proposal_id

    return [
        value.model_copy(
            update={
                "proposal": rewrite_proposal_ids(
                    value.proposal,
                    proposal_id=resolve(
                        type(value.proposal).__name__, value.proposal.proposal_id
                    ),
                    resolve=resolve,
                )
            }
        )
        for value in values
    ]


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


def _relationship_participant_key(
    participant: RelationshipParticipantRefV1,
) -> tuple[object, ...]:
    return (
        participant.mention_text,
        participant.participant_kind,
        participant.resolution_status,
        participant.entity_proposal_id,
        participant.proposal_schema,
    )


def _relationship_signal_key(proposal: RelationshipSignalProposalV1) -> tuple[object, ...]:
    """Return the complete exact relationship semantics key without canonical linking."""

    participants = [
        _relationship_participant_key(proposal.subject),
        _relationship_participant_key(proposal.counterpart),
    ]
    if proposal.directionality == RelationshipDirectionality.SYMMETRIC:
        participants.sort(key=repr)
    speaker = (
        _relationship_participant_key(proposal.source_speaker)
        if proposal.source_speaker is not None
        else None
    )
    context_event = (
        (
            proposal.context_event.event_summary,
            proposal.context_event.resolution_status,
            proposal.context_event.event_proposal_id,
            proposal.context_event.proposal_schema,
        )
        if proposal.context_event is not None
        else None
    )
    anchor = proposal.temporal_anchor
    return (
        tuple(participants),
        proposal.relationship_domain,
        proposal.relationship_kind,
        proposal.directionality,
        proposal.signal_effect,
        proposal.assertion_polarity,
        proposal.evidence_basis,
        proposal.support_level,
        speaker,
        context_event,
        (
            anchor.valid_from,
            anchor.valid_until,
            anchor.anchor_text,
            anchor.resolution_status,
            anchor.event_proposal_id,
            anchor.proposal_schema,
        ),
        proposal.reality_layer,
    )
