"""Deterministically namespace window-local Narrative proposal identifiers."""

from collections.abc import Callable, Mapping

from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    ClaimSourceType,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    RelationshipSignalProposalV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.workflow import NarrativeAnalysisProposalSourceV1
from comic_agent.services.id_service import stable_id

Proposal = (
    EventProposalV1
    | EntityProposalV1
    | ClaimProposalV1
    | KnowledgeStateProposalV1
    | StateChangeProposalV1
    | RelationshipSignalProposalV1
    | CampusContentProfileProposalV1
)
IdResolver = Callable[[str, str | None], str | None]


def proposal_window_scope(
    analysis_run_id: str, window_index: int, chunk_ids: list[str]
) -> str:
    """Identify one logical source window consistently across Narrative modes."""

    return stable_id(
        "narrative-proposal-window", analysis_run_id, window_index, ",".join(chunk_ids)
    )


def normalize_proposal_sources(
    sources: list[NarrativeAnalysisProposalSourceV1],
    *,
    analysis_run_id: str,
    source_scopes: Mapping[str, str] | None = None,
) -> list[NarrativeAnalysisProposalSourceV1]:
    """Namespace every local id and rewrite references within the same logical window."""

    scopes = source_scopes or {}
    id_map: dict[tuple[str, str, str], str] = {}
    for source in sources:
        scope = scopes.get(source.agent_run_id, source.agent_run_id)
        schema = type(source.proposal).__name__
        local_id = source.proposal.proposal_id
        id_map[(scope, schema, local_id)] = stable_id(
            "narrative-proposal", analysis_run_id, scope, schema, local_id
        )

    normalized: list[NarrativeAnalysisProposalSourceV1] = []
    for source in sources:
        scope = scopes.get(source.agent_run_id, source.agent_run_id)

        def resolve(
            schema: str, local_id: str | None, scope: str = scope
        ) -> str | None:
            if local_id is None:
                return None
            return id_map.get((scope, schema, local_id), local_id)

        schema = type(source.proposal).__name__
        proposal = rewrite_proposal_ids(
            source.proposal,
            proposal_id=resolve(schema, source.proposal.proposal_id),
            resolve=resolve,
        )
        normalized.append(source.model_copy(update={"proposal": proposal}))
    return normalized


def rewrite_proposal_ids(
    proposal: Proposal,
    *,
    proposal_id: str | None,
    resolve: IdResolver,
) -> Proposal:
    """Rewrite one proposal and every typed candidate reference it owns."""

    if proposal_id is None:
        raise ValueError("normalized proposal_id cannot be null")
    update: dict[str, object] = {"proposal_id": proposal_id}
    if isinstance(proposal, EntityProposalV1):
        return proposal.model_copy(update=update)
    if isinstance(proposal, EventProposalV1):
        update.update(
            participant_ids=[
                resolve("EntityProposalV1", item) or item for item in proposal.participant_ids
            ],
            location_id=resolve("EntityProposalV1", proposal.location_id),
        )
    elif isinstance(proposal, ClaimProposalV1):
        update.update(target_event_id=resolve("EventProposalV1", proposal.target_event_id))
        if proposal.schema_version == "1.0":
            update.update(
                claim_id=proposal_id,
                subject_id=resolve("EntityProposalV1", proposal.subject_id),
                asserted_by_entity_id=resolve(
                    "EntityProposalV1", proposal.asserted_by_entity_id
                ),
            )
        elif proposal.source_type == ClaimSourceType.CHARACTER:
            update["source_id"] = resolve("EntityProposalV1", proposal.source_id)
    elif isinstance(proposal, KnowledgeStateProposalV1):
        if proposal.schema_version == "1.0":
            update.update(
                character_id=resolve("EntityProposalV1", proposal.character_id),
                knowledge_target_id=resolve("ClaimProposalV1", proposal.knowledge_target_id),
                source_claim_id=resolve("ClaimProposalV1", proposal.source_claim_id),
                valid_from_event_id=resolve(
                    "EventProposalV1", proposal.valid_from_event_id
                ),
            )
        else:
            if proposal.subject is not None:
                update["subject"] = proposal.subject.model_copy(
                    update={
                        "entity_proposal_id": resolve(
                            "EntityProposalV1", proposal.subject.entity_proposal_id
                        )
                    }
                )
            if proposal.target is not None:
                update["target"] = proposal.target.model_copy(
                    update={
                        "proposal_id": resolve(
                            proposal.target.proposal_schema or "",
                            proposal.target.proposal_id,
                        )
                    }
                )
            update["supporting_claim_proposal_id"] = resolve(
                "ClaimProposalV1", proposal.supporting_claim_proposal_id
            )
            for field in ("valid_from", "valid_until"):
                anchor = getattr(proposal, field)
                if anchor is not None:
                    update[field] = anchor.model_copy(
                        update={
                            "event_proposal_id": resolve(
                                "EventProposalV1", anchor.event_proposal_id
                            )
                        }
                    )
    elif isinstance(proposal, StateChangeProposalV1):
        if proposal.schema_version == "1.0":
            update.update(
                event_id=resolve("EventProposalV1", proposal.event_id),
                target_entity_id=resolve("EntityProposalV1", proposal.target_entity_id),
            )
        else:
            if proposal.event is not None:
                update["event"] = proposal.event.model_copy(
                    update={
                        "event_proposal_id": resolve(
                            "EventProposalV1", proposal.event.event_proposal_id
                        )
                    }
                )
            if proposal.target is not None:
                update["target"] = proposal.target.model_copy(
                    update={
                        "entity_proposal_id": resolve(
                            "EntityProposalV1", proposal.target.entity_proposal_id
                        )
                    }
                )
    elif isinstance(proposal, RelationshipSignalProposalV1):
        for field in ("subject", "counterpart", "source_speaker"):
            participant = getattr(proposal, field)
            if participant is not None:
                update[field] = participant.model_copy(
                    update={
                        "entity_proposal_id": resolve(
                            "EntityProposalV1", participant.entity_proposal_id
                        )
                    }
                )
        if proposal.context_event is not None:
            update["context_event"] = proposal.context_event.model_copy(
                update={
                    "event_proposal_id": resolve(
                        "EventProposalV1", proposal.context_event.event_proposal_id
                    )
                }
            )
        update["temporal_anchor"] = proposal.temporal_anchor.model_copy(
            update={
                "event_proposal_id": resolve(
                    "EventProposalV1", proposal.temporal_anchor.event_proposal_id
                )
            }
        )
    elif isinstance(proposal, CampusContentProfileProposalV1):
        update["must_preserve_fact_ids"] = [
            resolve("ClaimProposalV1", item) or item
            for item in proposal.must_preserve_fact_ids
        ]
    return proposal.model_copy(update=update)
