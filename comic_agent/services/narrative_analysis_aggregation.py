"""Typed, conservative aggregation for whole-document proposal candidates."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import ClaimProposalV1, EntityProposalV1, EventProposalV1
from comic_agent.schemas.workflow import (
    AggregatedClaimProposalV1,
    AggregatedEntityProposalV1,
    AggregatedEventProposalV1,
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
    return NarrativeAnalysisResultV1(
        analysis_run_id=analysis_run_id,
        events=list(events.values()),
        entities=list(entities.values()),
        claims=list(claims.values()),
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
