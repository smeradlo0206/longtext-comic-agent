"""Sanitized NarrativeAnalyst smoke/API summary helpers."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from comic_agent.config import Settings
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    ClaimProposalV1,
    EntityProposalBatchV1,
    EntityProposalV1,
    EventProposalBatchV1,
    EventProposalV1,
    KnowledgeStateProposalBatchV1,
    KnowledgeStateProposalV1,
    StateChangeProposalBatchV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import AgentContext

DEFAULT_MAX_CHARS_PER_CHUNK = 1200
SELECTED_CHUNK_PREVIEW_CHARS = 60


@dataclass(frozen=True)
class EvidenceNormalizationResult:
    """Proposal plus audit counts for deterministic evidence normalization."""

    proposal: BaseModel
    rebound_chunk_ids: int
    rebased_quote_ranges: int
    cleared_quote_ranges: int


FAILURE_RECOMMENDED_ACTIONS = {
    "PROVIDER_TIMEOUT": "increase timeout or reduce max_chars_per_chunk",
    "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT": (
        "reduce max_chars_per_chunk before raising max output tokens"
    ),
    "PROVIDER_CONTENT_MISSING": "disable response_format or reduce input budget",
    "PROVIDER_INVALID_JSON": "retry with a smaller input budget or a JSON-capable chat model",
    "PROVIDER_HTTP_ERROR": "check provider status, model name, and request settings",
    "PROVIDER_CONNECTION_ERROR": "check campus network, VPN, and provider endpoint reachability",
    "PROVIDER_RESPONSE_FORMAT_INVALID": "retry once and inspect sanitized provider diagnostics",
    "SCHEMA_VALIDATION_FAILED": "inspect provider JSON shape and mode boundary",
    "EVIDENCE_VALIDATION_FAILED": "manual review evidence fields against selected context",
    "QUOTE_NOT_MATCHED": "tighten exact quote prompt and use shorter verbatim quote",
    "CHAR_RANGE_NOT_MATCHED": "tighten exact quote prompt or omit uncertain char ranges",
    "MODE_NOT_IMPLEMENTED": "select an implemented NarrativeAnalyst mode",
    "REAL_LLM_DISABLED": "restart the API with ENABLE_REAL_LLM=true",
    "UNKNOWN_ERROR": "manual review sanitized error diagnostics",
}

SANITIZED_DIAGNOSTIC_KEYS = {
    "finish_reason",
    "response_has_choices",
    "choices_count",
    "message_keys",
    "content_type",
    "content_length",
    "has_reasoning_content",
    "has_tool_calls",
    "usage_prompt_tokens",
    "usage_completion_tokens",
    "usage_total_tokens",
    "timeout_kind",
    "timeout_seconds",
    "request_attempts",
    "http_status_code",
    "schema_error_kind",
    "schema_error_field_paths",
    "schema_error_rule_codes",
    "expected_output_schema",
}


def implemented_mode_names() -> list[str]:
    """Return modes implemented by NarrativeAnalyst v0.1."""

    return [
        "event_extraction",
        "entity_extraction",
        "claim_extraction",
        "knowledge_state_extraction",
        "state_change_extraction",
    ]


def base_eval_summary(
    *,
    project_id: str,
    mode: str,
    real_llm_requested: bool,
    real_llm_enabled: bool,
    provider_name: str,
    model: str,
    chunk_limit: int,
    chunk_offset: int,
    max_chars_per_chunk: int,
    selected_chunks: list[SourceChunkV1],
    output_schema: str | None,
    import_idempotent: bool | None = None,
) -> dict[str, Any]:
    """Build the common sanitized evaluation summary shape."""

    input_budget = input_budget_summary(selected_chunks, max_chars_per_chunk)
    return {
        "project_id": project_id,
        "mode": mode,
        "dry_run": not real_llm_requested,
        "real_llm_requested": real_llm_requested,
        "real_llm_enabled": real_llm_enabled,
        "real_llm_called": False,
        "provider_name": provider_name,
        "model": model,
        "import_idempotent": import_idempotent,
        "context_chunk_ids": [],
        "chunk_limit": chunk_limit,
        "chunk_offset": chunk_offset,
        "selected_chunks_count": len(selected_chunks),
        "max_chars_per_chunk": max_chars_per_chunk,
        "input_chars_total": input_budget["input_chars_total"],
        "truncated_chunks_count": input_budget["truncated_chunks_count"],
        "agent_run_saved": False,
        "agent_run_id": None,
        "agent_run_status": None,
        "provider_result_id": None,
        "provider_success": None,
        "provider_error_diagnostics": None,
        "usage_prompt_tokens": None,
        "usage_completion_tokens": None,
        "usage_total_tokens": None,
        "output_schema": output_schema,
        "schema_validation_passed": None,
        "evidence_validation_passed": None,
        "quote_matched": None,
        "char_range_matched": None,
        "error_message": None,
        "failure_category": None,
        "recommended_action": None,
        "manual_score": None,
        "manual_issue": None,
    }


def selected_chunk_metadata(
    chunks: list[SourceChunkV1],
    *,
    chapter_titles: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return short, sanitized metadata for chunks selected for a run."""

    titles = chapter_titles or {}
    items: list[dict[str, object]] = []
    for chunk in chunks:
        preview = _safe_preview(chunk.text)
        items.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "chapter_id": chunk.chapter_id,
                "chapter_title": titles.get(chunk.chapter_id),
                "preview": preview,
                "preview_length": len(preview),
                "text_length": len(chunk.text),
            }
        )
    return items


def _safe_preview(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return ""
    if len(compact) > SELECTED_CHUNK_PREVIEW_CHARS:
        return compact[:SELECTED_CHUNK_PREVIEW_CHARS].rstrip()
    if len(compact) == 1:
        return "..."
    visible_chars = min(20, len(compact) - 1)
    return f"{compact[:visible_chars].rstrip()}..."


def visible_context_chunks(
    chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> list[SourceChunkV1]:
    """Return SourceChunk copies with text limited for LLM input."""

    return [chunk.model_copy(update={"text": chunk.text[:max_chars_per_chunk]}) for chunk in chunks]


def input_budget_summary(
    chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> dict[str, int]:
    """Return sanitized input-budget metadata."""

    return {
        "input_chars_total": sum(min(len(chunk.text), max_chars_per_chunk) for chunk in chunks),
        "truncated_chunks_count": sum(len(chunk.text) > max_chars_per_chunk for chunk in chunks),
    }


def slim_input_context(
    context: AgentContext,
    visible_chunks: list[SourceChunkV1],
    *,
    full_source_chunk_records: bool = False,
) -> dict[str, object]:
    """Build a bounded SourceChunk payload for one Agent context."""

    source_chunks: list[dict[str, object]]
    if full_source_chunk_records:
        source_chunks = [chunk.model_dump(mode="json") for chunk in visible_chunks]
    else:
        source_chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "chapter_id": chunk.chapter_id,
                "text": chunk.text,
            }
            for chunk in visible_chunks
        ]

    return {
        "project_id": context.project_id,
        "source_chunk_ids": context.source_chunk_ids,
        "source_chunks": source_chunks,
    }


def normalize_proposal_evidence(
    proposal: BaseModel,
    selected_chunks: list[SourceChunkV1],
) -> EvidenceNormalizationResult:
    """Repair only uniquely verifiable evidence references from bounded context."""

    if isinstance(proposal, EventProposalBatchV1):
        events, counts = _normalize_proposal_items(proposal.events, selected_chunks)
        return EvidenceNormalizationResult(
            proposal=proposal.model_copy(update={"events": events}),
            **counts,
        )
    if isinstance(proposal, EntityProposalBatchV1):
        entities, counts = _normalize_proposal_items(proposal.entities, selected_chunks)
        return EvidenceNormalizationResult(
            proposal=proposal.model_copy(update={"entities": entities}),
            **counts,
        )
    if isinstance(proposal, ClaimProposalBatchV1):
        claims, counts = _normalize_proposal_items(proposal.claims, selected_chunks)
        return EvidenceNormalizationResult(
            proposal=proposal.model_copy(update={"claims": claims}),
            **counts,
        )
    if isinstance(proposal, KnowledgeStateProposalBatchV1):
        states, counts = _normalize_proposal_items(proposal.states, selected_chunks)
        return EvidenceNormalizationResult(
            proposal=proposal.model_copy(update={"states": states}),
            **counts,
        )
    if isinstance(proposal, StateChangeProposalBatchV1):
        changes, counts = _normalize_proposal_items(proposal.changes, selected_chunks)
        return EvidenceNormalizationResult(
            proposal=proposal.model_copy(update={"changes": changes}),
            **counts,
        )
    if isinstance(
        proposal,
        (
            EventProposalV1,
            EntityProposalV1,
            ClaimProposalV1,
            KnowledgeStateProposalV1,
            StateChangeProposalV1,
        ),
    ):
        items, counts = _normalize_proposal_items([proposal], selected_chunks)
        return EvidenceNormalizationResult(proposal=items[0], **counts)
    return EvidenceNormalizationResult(
        proposal=proposal,
        rebound_chunk_ids=0,
        rebased_quote_ranges=0,
        cleared_quote_ranges=0,
    )


def _normalize_proposal_items(
    items: Sequence[
        EventProposalV1
        | EntityProposalV1
        | ClaimProposalV1
        | KnowledgeStateProposalV1
        | StateChangeProposalV1
    ],
    selected_chunks: list[SourceChunkV1],
) -> tuple[
    list[
        EventProposalV1
        | EntityProposalV1
        | ClaimProposalV1
        | KnowledgeStateProposalV1
        | StateChangeProposalV1
    ],
    dict[str, int],
]:
    normalized_items: list[
        EventProposalV1
        | EntityProposalV1
        | ClaimProposalV1
        | KnowledgeStateProposalV1
        | StateChangeProposalV1
    ] = []
    counts = {
        "rebound_chunk_ids": 0,
        "rebased_quote_ranges": 0,
        "cleared_quote_ranges": 0,
    }
    for item in items:
        evidence_refs, item_counts = _normalize_evidence_refs(item.evidence_refs, selected_chunks)
        normalized_items.append(item.model_copy(update={"evidence_refs": evidence_refs}))
        for key, value in item_counts.items():
            counts[key] += value
    return normalized_items, counts


def _normalize_evidence_refs(
    evidence_refs: list[EvidenceRefV1],
    selected_chunks: list[SourceChunkV1],
) -> tuple[list[EvidenceRefV1], dict[str, int]]:
    """Rebind unique exact quotes and convert their offsets to local chunk coordinates."""

    chunks_by_id = {chunk.chunk_id: chunk for chunk in selected_chunks}
    normalized_refs: list[EvidenceRefV1] = []
    counts = {
        "rebound_chunk_ids": 0,
        "rebased_quote_ranges": 0,
        "cleared_quote_ranges": 0,
    }
    for evidence_ref in evidence_refs:
        quote_text = evidence_ref.quote_text
        evidence_chunk = chunks_by_id.get(evidence_ref.chunk_id)
        updates: dict[str, object] = {}

        if quote_text is not None:
            matching_chunks = [chunk for chunk in selected_chunks if quote_text in chunk.text]
            if evidence_chunk not in matching_chunks and len(matching_chunks) == 1:
                evidence_chunk = matching_chunks[0]
                updates["chunk_id"] = evidence_chunk.chunk_id
                counts["rebound_chunk_ids"] += 1

            if evidence_chunk is not None and evidence_chunk in matching_chunks:
                quote_start = evidence_ref.quote_start
                quote_end = evidence_ref.quote_end
                if quote_start is not None and quote_end is not None:
                    range_matches = (
                        0 <= quote_start <= quote_end <= len(evidence_chunk.text)
                        and evidence_chunk.text[quote_start:quote_end] == quote_text
                    )
                    if not range_matches:
                        local_starts = _all_occurrence_starts(evidence_chunk.text, quote_text)
                        if len(local_starts) == 1:
                            local_start = local_starts[0]
                            updates["quote_start"] = local_start
                            updates["quote_end"] = local_start + len(quote_text)
                            counts["rebased_quote_ranges"] += 1
                        else:
                            updates["quote_start"] = None
                            updates["quote_end"] = None
                            counts["cleared_quote_ranges"] += 1

        normalized_refs.append(evidence_ref.model_copy(update=updates))
    return normalized_refs, counts


def _all_occurrence_starts(text: str, quote_text: str) -> list[int]:
    """Return every start offset for an exact substring, including overlapping matches."""

    starts: list[int] = []
    search_start = 0
    while True:
        found_at = text.find(quote_text, search_start)
        if found_at == -1:
            return starts
        starts.append(found_at)
        search_start = found_at + 1


def add_proposal_details(
    *,
    summary: dict[str, Any],
    proposal: BaseModel,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add mode-specific sanitized proposal metadata to a summary."""

    if isinstance(proposal, EventProposalBatchV1):
        add_event_batch_details(
            summary=summary,
            batch=proposal,
            selected_chunks=selected_chunks,
        )
        return
    if isinstance(proposal, EntityProposalBatchV1):
        add_entity_batch_details(
            summary=summary,
            batch=proposal,
            selected_chunks=selected_chunks,
        )
        return
    if isinstance(proposal, ClaimProposalBatchV1):
        add_claim_batch_details(
            summary=summary,
            batch=proposal,
            selected_chunks=selected_chunks,
        )
        return
    if isinstance(proposal, KnowledgeStateProposalBatchV1):
        add_knowledge_state_batch_details(
            summary=summary,
            batch=proposal,
            selected_chunks=selected_chunks,
        )
        return
    if isinstance(proposal, StateChangeProposalBatchV1):
        add_state_change_batch_details(
            summary=summary,
            batch=proposal,
            selected_chunks=selected_chunks,
        )
        return
    if isinstance(proposal, EventProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["event_type"] = proposal.event_type
        summary["actor_resolution_status"] = proposal.actor_resolution_status
        summary["confidence"] = proposal.confidence
        summary.update(validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, EntityProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["entity_type"] = proposal.entity_type
        summary["aliases_count"] = len(proposal.aliases)
        summary["confidence"] = proposal.confidence
        summary.update(validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, ClaimProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["claim_type"] = str(proposal.claim_type)
        summary["source_type"] = str(proposal.source_type)
        summary["verification_status"] = str(proposal.verification_status)
        summary["confidence"] = proposal.confidence
        summary.update(validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, KnowledgeStateProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["epistemic_status"] = str(proposal.epistemic_status)
        summary["epistemic_basis"] = str(proposal.epistemic_basis)
        summary["confidence"] = proposal.confidence
        summary.update(validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, StateChangeProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["attribute_path"] = str(proposal.attribute_path)
        summary["confidence"] = proposal.confidence
        summary.update(validate_evidence(proposal.evidence_refs, selected_chunks))


def add_event_batch_details(
    *,
    summary: dict[str, Any],
    batch: EventProposalBatchV1,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add sanitized EventProposalBatchV1 metadata to a summary."""

    first_event = batch.events[0]
    evidence_results = [_event_evidence_summary(event, selected_chunks) for event in batch.events]
    summary["batch_id"] = batch.batch_id
    summary["events_count"] = len(batch.events)
    summary["event_proposal_ids"] = [event.proposal_id for event in batch.events]
    summary["primary_event_type"] = first_event.event_type
    summary["primary_event_summary"] = _safe_summary(first_event.summary)
    summary["event_evidence_results"] = [
        {
            "proposal_id": result["proposal_id"],
            "event_type": result["event_type"],
            "evidence_chunk_id": result["evidence_chunk_id"],
            "quote_matched": result["quote_matched"],
            "char_range_matched": result["char_range_matched"],
        }
        for result in evidence_results
    ]
    summary["evidence_validation_passed"] = all(
        result["evidence_validation_passed"] is True for result in evidence_results
    )
    summary["quote_matched"] = _combine_tristate(
        [result["quote_matched"] for result in evidence_results]
    )
    summary["char_range_matched"] = _combine_tristate(
        [result["char_range_matched"] for result in evidence_results]
    )


def add_entity_batch_details(
    *,
    summary: dict[str, Any],
    batch: EntityProposalBatchV1,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add sanitized EntityProposalBatchV1 metadata to a summary."""

    evidence_results = [
        _entity_evidence_summary(entity, selected_chunks) for entity in batch.entities
    ]
    summary["batch_id"] = batch.batch_id
    summary["entities_count"] = len(batch.entities)
    summary["entity_proposal_ids"] = [entity.proposal_id for entity in batch.entities]
    summary["entity_evidence_results"] = [
        {
            "proposal_id": result["proposal_id"],
            "entity_type": result["entity_type"],
            "creature_subtype": result["creature_subtype"],
            "evidence_chunk_id": result["evidence_chunk_id"],
            "quote_matched": result["quote_matched"],
            "char_range_matched": result["char_range_matched"],
        }
        for result in evidence_results
    ]
    summary["evidence_validation_passed"] = all(
        result["evidence_validation_passed"] is True for result in evidence_results
    )
    summary["quote_matched"] = _combine_tristate(
        [result["quote_matched"] for result in evidence_results]
    )
    summary["char_range_matched"] = _combine_tristate(
        [result["char_range_matched"] for result in evidence_results]
    )


def add_claim_batch_details(
    *,
    summary: dict[str, Any],
    batch: ClaimProposalBatchV1,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add sanitized ClaimProposalBatchV1 metadata to a summary."""

    evidence_results = [_claim_evidence_summary(claim, selected_chunks) for claim in batch.claims]
    summary["batch_id"] = batch.batch_id
    summary["claims_count"] = len(batch.claims)
    summary["claim_proposal_ids"] = [claim.proposal_id for claim in batch.claims]
    summary["claim_evidence_results"] = [
        {
            "proposal_id": result["proposal_id"],
            "claim_type": result["claim_type"],
            "source_type": result["source_type"],
            "temporal_scope": result["temporal_scope"],
            "evidence_chunk_id": result["evidence_chunk_id"],
            "quote_matched": result["quote_matched"],
            "char_range_matched": result["char_range_matched"],
        }
        for result in evidence_results
    ]
    summary["evidence_validation_passed"] = all(
        result["evidence_validation_passed"] is True for result in evidence_results
    )
    summary["quote_matched"] = _combine_tristate(
        [result["quote_matched"] for result in evidence_results]
    )
    summary["char_range_matched"] = _combine_tristate(
        [result["char_range_matched"] for result in evidence_results]
    )


def add_knowledge_state_batch_details(
    *,
    summary: dict[str, Any],
    batch: KnowledgeStateProposalBatchV1,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add sanitized KnowledgeStateProposalBatchV1 metadata to a summary."""

    evidence_results = [
        _knowledge_state_evidence_summary(state, selected_chunks) for state in batch.states
    ]
    summary["batch_id"] = batch.batch_id
    summary["states_count"] = len(batch.states)
    summary["state_proposal_ids"] = [state.proposal_id for state in batch.states]
    summary["knowledge_state_evidence_results"] = [
        {
            "proposal_id": result["proposal_id"],
            "epistemic_status": result["epistemic_status"],
            "epistemic_basis": result["epistemic_basis"],
            "subject_resolution_status": result["subject_resolution_status"],
            "target_resolution_status": result["target_resolution_status"],
            "evidence_chunk_id": result["evidence_chunk_id"],
            "quote_matched": result["quote_matched"],
            "char_range_matched": result["char_range_matched"],
        }
        for result in evidence_results
    ]
    summary["evidence_validation_passed"] = all(
        result["evidence_validation_passed"] is True for result in evidence_results
    )
    summary["quote_matched"] = _combine_tristate(
        [result["quote_matched"] for result in evidence_results]
    )
    summary["char_range_matched"] = _combine_tristate(
        [result["char_range_matched"] for result in evidence_results]
    )


def add_state_change_batch_details(
    *,
    summary: dict[str, Any],
    batch: StateChangeProposalBatchV1,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add sanitized StateChangeProposalBatchV1 metadata to a summary."""

    evidence_results = [
        _state_change_evidence_summary(change, selected_chunks) for change in batch.changes
    ]
    summary["batch_id"] = batch.batch_id
    summary["changes_count"] = len(batch.changes)
    summary["change_proposal_ids"] = [change.proposal_id for change in batch.changes]
    summary["state_change_evidence_results"] = [
        {
            "proposal_id": result["proposal_id"],
            "attribute_path": result["attribute_path"],
            "target_resolution_status": result["target_resolution_status"],
            "evidence_chunk_id": result["evidence_chunk_id"],
            "quote_matched": result["quote_matched"],
            "char_range_matched": result["char_range_matched"],
        }
        for result in evidence_results
    ]
    summary["evidence_validation_passed"] = all(
        result["evidence_validation_passed"] is True for result in evidence_results
    )
    summary["quote_matched"] = _combine_tristate(
        [result["quote_matched"] for result in evidence_results]
    )
    summary["char_range_matched"] = _combine_tristate(
        [result["char_range_matched"] for result in evidence_results]
    )


def _event_evidence_summary(
    event: EventProposalV1,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    validation = validate_evidence_refs(event.evidence_refs, selected_chunks)
    return {
        "proposal_id": event.proposal_id,
        "event_type": event.event_type,
        **validation,
    }


def _entity_evidence_summary(
    entity: EntityProposalV1,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    validation = validate_evidence_refs(entity.evidence_refs, selected_chunks)
    return {
        "proposal_id": entity.proposal_id,
        "entity_type": entity.entity_type,
        "creature_subtype": entity.creature_subtype,
        **validation,
    }


def _claim_evidence_summary(
    claim: ClaimProposalV1,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    validation = validate_evidence_refs(claim.evidence_refs, selected_chunks)
    return {
        "proposal_id": claim.proposal_id,
        "claim_type": str(claim.claim_type),
        "source_type": str(claim.source_type),
        "temporal_scope": str(claim.temporal_scope) if claim.temporal_scope is not None else None,
        **validation,
    }


def _knowledge_state_evidence_summary(
    state: KnowledgeStateProposalV1,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    validation = validate_evidence_refs(state.evidence_refs, selected_chunks)
    return {
        "proposal_id": state.proposal_id,
        "epistemic_status": str(state.epistemic_status),
        "epistemic_basis": str(state.epistemic_basis),
        "subject_resolution_status": (
            str(state.subject.resolution_status) if state.subject is not None else None
        ),
        "target_resolution_status": (
            str(state.target.resolution_status) if state.target is not None else None
        ),
        **validation,
    }


def _state_change_evidence_summary(
    change: StateChangeProposalV1,
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    validation = validate_evidence_refs(change.evidence_refs, selected_chunks)
    return {
        "proposal_id": change.proposal_id,
        "attribute_path": str(change.attribute_path),
        "target_resolution_status": (
            str(change.target.resolution_status) if change.target is not None else None
        ),
        **validation,
    }


def validate_evidence(
    evidence_refs: list[Any],
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    """Validate the first EvidenceRef against selected visible chunks."""

    if not evidence_refs:
        return {
            "evidence_validation_passed": False,
            "evidence_chunk_id": None,
            "quote_matched": None,
            "char_range_matched": None,
        }

    evidence_ref = evidence_refs[0]
    evidence_chunk = next(
        (chunk for chunk in selected_chunks if chunk.chunk_id == evidence_ref.chunk_id),
        None,
    )
    result: dict[str, Any] = {
        "evidence_chunk_id": evidence_ref.chunk_id,
        "quote_matched": None,
        "char_range_matched": None,
    }
    if evidence_chunk is None:
        result["evidence_validation_passed"] = False
        result["quote_matched"] = False if evidence_ref.quote_text is not None else None
        result["char_range_matched"] = False if evidence_ref.quote_start is not None else None
        return result

    evidence_valid = True
    if evidence_ref.quote_text is not None:
        quote_matched = evidence_ref.quote_text in evidence_chunk.text
        result["quote_matched"] = quote_matched
        evidence_valid = evidence_valid and quote_matched

    has_range = evidence_ref.quote_start is not None and evidence_ref.quote_end is not None
    if has_range:
        quote_start = evidence_ref.quote_start
        quote_end = evidence_ref.quote_end
        range_in_bounds = 0 <= quote_start <= quote_end <= len(evidence_chunk.text)
        if not range_in_bounds:
            result["char_range_matched"] = False
            result["evidence_validation_passed"] = False
            return result
        ranged_text = evidence_chunk.text[quote_start:quote_end]
        char_range_matched = (
            ranged_text == evidence_ref.quote_text if evidence_ref.quote_text is not None else True
        )
        result["char_range_matched"] = char_range_matched
        evidence_valid = evidence_valid and char_range_matched

    result["evidence_validation_passed"] = evidence_valid
    return result


def validate_evidence_refs(
    evidence_refs: list[Any],
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
    """Validate all EvidenceRef records and aggregate sanitized status."""

    if not evidence_refs:
        return {
            "evidence_validation_passed": False,
            "evidence_chunk_id": None,
            "quote_matched": None,
            "char_range_matched": None,
        }

    results = [validate_evidence([evidence_ref], selected_chunks) for evidence_ref in evidence_refs]
    return {
        "evidence_validation_passed": all(
            result["evidence_validation_passed"] is True for result in results
        ),
        "evidence_chunk_id": results[0]["evidence_chunk_id"],
        "quote_matched": _combine_tristate([result["quote_matched"] for result in results]),
        "char_range_matched": _combine_tristate(
            [result["char_range_matched"] for result in results]
        ),
    }


def _combine_tristate(values: list[Any]) -> bool | None:
    if any(value is False for value in values):
        return False
    if any(value is True for value in values):
        return True
    return None


def _safe_summary(summary: str, limit: int = 80) -> str:
    compact = " ".join(summary.split())
    if len(compact) > limit:
        return compact[:limit].rstrip()
    return compact


def add_provider_diagnostics(summary: dict[str, Any], exc: BaseException) -> None:
    """Copy only whitelisted provider diagnostics onto the summary."""

    sanitized_diagnostics = sanitize_provider_diagnostics(getattr(exc, "diagnostics", None))
    if sanitized_diagnostics is None:
        return
    summary["provider_error_diagnostics"] = sanitized_diagnostics
    for key in (
        "usage_prompt_tokens",
        "usage_completion_tokens",
        "usage_total_tokens",
    ):
        if key in sanitized_diagnostics:
            summary[key] = sanitized_diagnostics[key]


def sanitize_provider_diagnostics(diagnostics: object) -> dict[str, object] | None:
    """Return only the fixed allowlist of provider diagnostic metadata."""

    if not isinstance(diagnostics, dict):
        return None
    sanitized = {
        key: value for key, value in diagnostics.items() if key in SANITIZED_DIAGNOSTIC_KEYS
    }
    return sanitized or None


def classify_exception(exc: BaseException) -> str:
    """Return a sanitized failure category for provider/workflow exceptions."""

    if isinstance(exc, TimeoutError):
        return "PROVIDER_TIMEOUT"
    if isinstance(exc, NotImplementedError):
        return "MODE_NOT_IMPLEMENTED"

    diagnostics = getattr(exc, "diagnostics", None)
    finish_reason = diagnostics.get("finish_reason") if isinstance(diagnostics, dict) else None
    content_type = diagnostics.get("content_type") if isinstance(diagnostics, dict) else None
    message = str(exc).lower()

    if finish_reason == "length" or "exceeded max output tokens" in message:
        return "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT"
    if "content is missing" in message or content_type == "NoneType":
        return "PROVIDER_CONTENT_MISSING"
    if "did not contain valid json" in message:
        return "PROVIDER_INVALID_JSON"
    if message.startswith("llm provider http error"):
        return "PROVIDER_HTTP_ERROR"
    if "llm provider connection" in message or "llm provider network" in message:
        return "PROVIDER_CONNECTION_ERROR"
    if "llm provider response format is invalid" in message:
        return "PROVIDER_RESPONSE_FORMAT_INVALID"
    if "schema validation" in message or "validation" in message:
        return "SCHEMA_VALIDATION_FAILED"
    return "UNKNOWN_ERROR"


def classify_evidence_result(summary: dict[str, Any]) -> None:
    """Classify evidence validation failures without exposing evidence text."""

    if summary.get("evidence_validation_passed") is not False:
        return
    if summary.get("quote_matched") is False:
        set_failure(summary, "QUOTE_NOT_MATCHED")
        return
    if summary.get("char_range_matched") is False:
        set_failure(summary, "CHAR_RANGE_NOT_MATCHED")
        return
    set_failure(summary, "EVIDENCE_VALIDATION_FAILED")


def set_failure(summary: dict[str, Any], category: str) -> None:
    """Set sanitized failure metadata."""

    summary["failure_category"] = category
    summary["recommended_action"] = recommended_action_for_failure(
        category,
        summary.get("provider_error_diagnostics"),
    )


def recommended_action_for_failure(
    category: str,
    diagnostics: object = None,
) -> str:
    """Return safe operator guidance, refining HTTP failures by status only."""

    if category == "PROVIDER_HTTP_ERROR" and isinstance(diagnostics, dict):
        status_code = diagnostics.get("http_status_code")
        if status_code == 429:
            return "wait before resume and keep concurrency at 1"
        if isinstance(status_code, int) and status_code >= 500:
            return "wait briefly and resume failed windows"
        if status_code == 400:
            return "check model, request shape, and response_format settings"
        if status_code in {401, 403}:
            return "check local provider credential or access settings"
        if status_code == 404:
            return "check provider endpoint and model name"
    return FAILURE_RECOMMENDED_ACTIONS[category]


def sanitize_error_message(
    message: str,
    *,
    settings: Settings,
    selected_chunks: list[SourceChunkV1],
) -> str:
    """Redact secrets and selected source text from an error message."""

    sanitized = message
    if settings.llm_api_key is not None:
        secret_value = settings.llm_api_key.get_secret_value()
        if secret_value:
            sanitized = sanitized.replace(secret_value, "[redacted-secret]")
    for chunk in selected_chunks:
        if chunk.text:
            sensitive_values = {
                chunk.text,
                chunk.text[:200],
                chunk.text[:100],
                chunk.text[:50],
            }
            for sensitive_value in sensitive_values:
                if sensitive_value:
                    sanitized = sanitized.replace(sensitive_value, "[redacted-source-text]")
    return sanitized


def manual_review_checklist(mode: str) -> dict[str, Any]:
    """Return a null-filled manual review checklist for the selected mode."""

    if mode == "event_extraction":
        return {
            "events_cover_major_plot_points": None,
            "event_count_reasonable": None,
            "no_duplicate_events": None,
            "no_invented_events": None,
            "every_event_has_supporting_evidence": None,
            "event_summaries_supported_by_quotes": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "entity_extraction":
        return {
            "entities_cover_major_entities": None,
            "entity_count_reasonable": None,
            "no_duplicate_entities": None,
            "entity_types_correct": None,
            "creature_classification_correct": None,
            "creature_subtype_supported_or_null": None,
            "important_unnamed_objects_allowed": None,
            "concept_is_not_a_catch_all": None,
            "names_and_aliases_not_invented": None,
            "every_entity_has_supporting_evidence": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "claim_extraction":
        return {
            "claims_cover_major_claims": None,
            "claim_count_reasonable": None,
            "no_duplicate_claims": None,
            "claim_is_attributable_proposition": None,
            "claim_type_matches_decision_table": None,
            "factual_assertions_are_unhedged": None,
            "belief_and_hypothesis_distinguished": None,
            "evaluation_and_interpretation_distinguished": None,
            "claim_temporal_scope_correct": None,
            "prediction_commitment_distinguished": None,
            "every_claim_has_supporting_evidence": None,
            "no_duplicate_or_invented_claims": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "knowledge_state_extraction":
        return {
            "knowledge_states_cover_explicit_epistemic_states": None,
            "no_state_inferred_from_speech_presence_or_silence": None,
            "knows_not_inferred_from_reader_or_narrator_knowledge": None,
            "subject_target_and_anchor_resolution_preserved": None,
            "every_knowledge_state_has_supporting_evidence": None,
            "no_status_upgrade_or_contradiction_adjudication": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "state_change_extraction":
        return {
            "state_changes_cover_explicit_object_state_changes": None,
            "event_and_target_remain_source_grounded": None,
            "attribute_path_matches_target_kind": None,
            "new_value_has_supporting_evidence": None,
            "persistence_is_not_inferred": None,
            "unresolved_references_are_not_upgraded": None,
            "manual_score": None,
            "manual_issue": None,
        }
    return {
        "manual_score": None,
        "manual_issue": None,
    }
