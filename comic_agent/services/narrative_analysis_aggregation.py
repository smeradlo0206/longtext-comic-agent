"""Typed, conservative aggregation for whole-document proposal candidates."""

import json
from collections import Counter

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeReferenceResolutionStatus,
    KnowledgeStateProposalV1,
    KnowledgeTemporalAnchorV1,
    ProposalMentionRefV1,
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
from comic_agent.services.id_service import stable_id


def aggregate_narrative_analysis(
    sources: list[NarrativeAnalysisProposalSourceV1],
    *,
    analysis_run_id: str = "aggregate-preview",
) -> NarrativeAnalysisResultV1:
    """Merge only exact documented keys; preserve all source run and evidence references."""

    sources = _normalize_parallel_reference_values(
        _repair_cross_window_proposal_id_collisions(sources)
    )
    events: dict[tuple[object, ...], AggregatedEventProposalV1] = {}
    entities: dict[tuple[object, ...], AggregatedEntityProposalV1] = {}
    claims: dict[tuple[object, ...], AggregatedClaimProposalV1] = {}
    knowledge_states: dict[tuple[object, ...], AggregatedKnowledgeStateProposalV1] = {}
    state_changes: dict[tuple[object, ...], AggregatedStateChangeProposalV1] = {}
    relationship_signals: dict[tuple[object, ...], AggregatedRelationshipSignalProposalV1] = {}
    campus_content_profiles: dict[tuple[object, ...], AggregatedCampusContentProfileProposalV1] = {}
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
        elif isinstance(proposal, RelationshipSignalProposalV1):
            relationship_key = _relationship_signal_key(proposal)
            existing_signal = relationship_signals.get(relationship_key)
            if existing_signal is None:
                relationship_signals[relationship_key] = AggregatedRelationshipSignalProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
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
            profile_key = (
                proposal.project_id,
                proposal.content_type,
                tuple(proposal.audience),
                tuple(proposal.must_preserve_fact_ids),
                proposal.tone,
                proposal.page_budget,
                _evidence_key(proposal.evidence_refs),
            )
            existing_profile = campus_content_profiles.get(profile_key)
            if existing_profile is None:
                campus_content_profiles[profile_key] = AggregatedCampusContentProfileProposalV1(
                    proposal=proposal,
                    agent_run_ids=[source.agent_run_id],
                    evidence_refs=proposal.evidence_refs,
                )
            else:
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
        events=list(events.values()),
        entities=list(entities.values()),
        claims=list(claims.values()),
        knowledge_states=list(knowledge_states.values()),
        state_changes=list(state_changes.values()),
        relationship_signals=list(relationship_signals.values()),
        campus_content_profiles=list(campus_content_profiles.values()),
    )


def _repair_cross_window_proposal_id_collisions(
    sources: list[NarrativeAnalysisProposalSourceV1],
) -> list[NarrativeAnalysisProposalSourceV1]:
    """Repair only colliding Provider-local ids before a whole-document review.

    Normal Proposal ids remain API-compatible. When separate windows produce the
    same schema/id pair, derive a deterministic aggregate candidate id from the
    validated Proposal value excluding that local sequence. This preserves the
    candidate's semantics and evidence while allowing Gate 2 to address it.
    """

    keys = [
        (type(source.proposal).__name__, source.proposal.proposal_id)
        for source in sources
    ]
    duplicate_keys = {key for key, count in Counter(keys).items() if count > 1}
    if not duplicate_keys:
        return sources

    repaired: list[NarrativeAnalysisProposalSourceV1] = []
    for source in sources:
        proposal = source.proposal
        key = (type(proposal).__name__, proposal.proposal_id)
        if key not in duplicate_keys:
            repaired.append(source)
            continue
        payload = proposal.model_dump(mode="json")
        payload.pop("proposal_id", None)
        repaired.append(
            source.model_copy(
                update={
                    "proposal": proposal.model_copy(
                        update={
                            "proposal_id": stable_id(
                                "narrative-proposal",
                                type(proposal).__name__,
                                json.dumps(
                                    payload,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                            )
                        }
                    )
                }
            )
        )
    return repaired


def _normalize_parallel_reference_values(
    sources: list[NarrativeAnalysisProposalSourceV1],
) -> list[NarrativeAnalysisProposalSourceV1]:
    """Turn provider-local labels into auditable mention references.

    Individual Narrative modes run in parallel.  A provider can copy a person
    name (for example ``Lin``), but it cannot know that another run happened to
    choose ``entity-lin`` as its Proposal id.  Only values that already name a
    proposal in the aggregate stay hard ids; every other legacy value becomes an
    unresolved mention for Gate 2's exact, non-fuzzy reference resolver.
    """

    entity_ids = {
        source.proposal.proposal_id
        for source in sources
        if isinstance(source.proposal, EntityProposalV1)
    }
    event_ids = {
        source.proposal.proposal_id
        for source in sources
        if isinstance(source.proposal, EventProposalV1)
    }
    claim_ids = {
        source.proposal.proposal_id
        for source in sources
        if isinstance(source.proposal, ClaimProposalV1)
    }

    normalized: list[NarrativeAnalysisProposalSourceV1] = []
    for source in sources:
        proposal = source.proposal
        if isinstance(proposal, EventProposalV1):
            retained_ids = [
                participant_id
                for participant_id in proposal.participant_ids
                if participant_id in entity_ids
            ]
            legacy_mentions = [
                ProposalMentionRefV1(
                    mention_text=participant_id,
                    resolution_status=KnowledgeReferenceResolutionStatus.UNRESOLVED,
                )
                for participant_id in proposal.participant_ids
                if participant_id not in entity_ids
            ]
            location_mention = proposal.location_mention
            location_id = proposal.location_id
            if location_id is not None and location_id not in entity_ids:
                location_mention = ProposalMentionRefV1(
                    mention_text=location_id,
                    resolution_status=KnowledgeReferenceResolutionStatus.UNRESOLVED,
                )
                location_id = None
            if (
                retained_ids != proposal.participant_ids
                or location_id != proposal.location_id
            ):
                proposal = proposal.model_copy(
                    update={
                        "schema_version": "1.1",
                        "participant_ids": retained_ids,
                        "participant_mentions": [*proposal.participant_mentions, *legacy_mentions],
                        "location_id": location_id,
                        "location_mention": location_mention,
                    }
                )
        elif isinstance(proposal, ClaimProposalV1):
            source_reference = proposal.source_reference
            source_id = proposal.source_id
            expected_source_ids = (
                entity_ids
                if str(proposal.source_type) == "CHARACTER"
                else entity_ids | event_ids | claim_ids
            )
            if source_id is not None and source_id not in expected_source_ids:
                source_reference = ProposalMentionRefV1(
                    mention_text=source_id,
                    resolution_status=KnowledgeReferenceResolutionStatus.UNRESOLVED,
                )
                source_id = None
            target_event_reference = proposal.target_event_reference
            target_event_id = proposal.target_event_id
            if target_event_id is not None and target_event_id not in event_ids:
                target_event_reference = ProposalMentionRefV1(
                    mention_text=target_event_id,
                    resolution_status=KnowledgeReferenceResolutionStatus.UNRESOLVED,
                )
                target_event_id = None
            if source_id != proposal.source_id or target_event_id != proposal.target_event_id:
                proposal = proposal.model_copy(
                    update={
                        "schema_version": "1.3",
                        "source_id": source_id,
                        "source_reference": source_reference,
                        "target_event_id": target_event_id,
                        "target_event_reference": target_event_reference,
                    }
                )
        normalized.append(source.model_copy(update={"proposal": proposal}))
    return normalized


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
