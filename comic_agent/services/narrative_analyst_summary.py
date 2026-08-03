"""Sanitized NarrativeAnalyst smoke/API summary helpers."""

from typing import Any

from pydantic import BaseModel

from comic_agent.config import Settings
from comic_agent.schemas.narrative import ClaimProposalV1, EntityProposalV1, EventProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import AgentContext

DEFAULT_MAX_CHARS_PER_CHUNK = 1200

FAILURE_RECOMMENDED_ACTIONS = {
    "PROVIDER_TIMEOUT": "increase timeout or reduce max_chars_per_chunk",
    "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT": (
        "reduce max_chars_per_chunk before raising max output tokens"
    ),
    "PROVIDER_CONTENT_MISSING": "disable response_format or reduce input budget",
    "SCHEMA_VALIDATION_FAILED": "inspect provider JSON shape and mode boundary",
    "EVIDENCE_VALIDATION_FAILED": "manual review evidence fields against selected context",
    "QUOTE_NOT_MATCHED": "tighten exact quote prompt and use shorter verbatim quote",
    "CHAR_RANGE_NOT_MATCHED": "tighten exact quote prompt or omit uncertain char ranges",
    "MODE_NOT_IMPLEMENTED": "select an implemented NarrativeAnalyst mode",
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
}


def implemented_mode_names() -> list[str]:
    """Return modes implemented by NarrativeAnalyst v0.1."""

    return ["event_extraction", "entity_extraction", "claim_extraction"]


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


def visible_context_chunks(
    chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> list[SourceChunkV1]:
    """Return SourceChunk copies with text limited for LLM input."""

    return [
        chunk.model_copy(update={"text": chunk.text[:max_chars_per_chunk]})
        for chunk in chunks
    ]


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
) -> dict[str, object]:
    """Build a SourceChunk payload containing only extraction-relevant fields."""

    return {
        "project_id": context.project_id,
        "source_chunk_ids": context.source_chunk_ids,
        "source_chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "chapter_id": chunk.chapter_id,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "text": chunk.text,
            }
            for chunk in visible_chunks
        ],
    }


def add_proposal_details(
    *,
    summary: dict[str, Any],
    proposal: BaseModel,
    selected_chunks: list[SourceChunkV1],
) -> None:
    """Add mode-specific sanitized proposal metadata to a summary."""

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
        summary["canonical_name"] = proposal.canonical_name
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


def add_provider_diagnostics(summary: dict[str, Any], exc: BaseException) -> None:
    """Copy only whitelisted provider diagnostics onto the summary."""

    diagnostics = getattr(exc, "diagnostics", None)
    if not isinstance(diagnostics, dict):
        return
    sanitized_diagnostics = {
        key: value for key, value in diagnostics.items() if key in SANITIZED_DIAGNOSTIC_KEYS
    }
    summary["provider_error_diagnostics"] = sanitized_diagnostics
    for key in (
        "usage_prompt_tokens",
        "usage_completion_tokens",
        "usage_total_tokens",
    ):
        if key in sanitized_diagnostics:
            summary[key] = sanitized_diagnostics[key]


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
    summary["recommended_action"] = FAILURE_RECOMMENDED_ACTIONS[category]


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
            "is_event": None,
            "event_type_correct": None,
            "evidence_supports_event": None,
            "salient_event": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "entity_extraction":
        return {
            "is_entity": None,
            "entity_type_correct": None,
            "canonical_name_correct": None,
            "evidence_supports_entity": None,
            "salient_entity": None,
            "manual_score": None,
            "manual_issue": None,
        }
    if mode == "claim_extraction":
        return {
            "is_claim": None,
            "claim_type_correct": None,
            "source_type_correct": None,
            "evidence_supports_claim": None,
            "salient_claim": None,
            "manual_score": None,
            "manual_issue": None,
        }
    return {
        "manual_score": None,
        "manual_issue": None,
    }
