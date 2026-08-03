"""Dry-run or explicitly run NarrativeAnalyst modes over local TXT chunks."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.config import Settings, get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.providers.openai_compatible import OpenAICompatibleLLMProvider
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import ClaimProposalV1, EntityProposalV1, EventProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text

DEFAULT_MAX_CHARS_PER_CHUNK = 1200


def run_smoke(
    *,
    mode: str,
    project_id: str,
    txt_path: Path,
    output_dir: Path,
    chunk_limit: int = 3,
    chunk_offset: int = 0,
    max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK,
    enable_real_llm: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run a sanitized NarrativeAnalyst smoke check."""

    if chunk_limit < 1:
        raise ValueError("chunk_limit must be at least 1")
    if chunk_offset < 0:
        raise ValueError("chunk_offset must be non-negative")
    if max_chars_per_chunk < 1:
        raise ValueError("max_chars_per_chunk must be at least 1")

    active_settings = settings or get_settings()
    text = txt_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(f"sqlite+pysqlite:///{output_dir / 'narrative_analyst_smoke.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    session: Session = session_factory()
    try:
        source_repository = SourceRepository(session)
        parsed = DocumentParser().parse_txt(
            project_id=project_id,
            filename=txt_path.name,
            text=text,
            storage_uri=f"local://{txt_path.name}",
        )
        first_import = source_repository.import_parsed_document(parsed)
        second_import = source_repository.import_parsed_document(parsed)
        chunks = source_repository.list_document_chunks(first_import.document.document_id)
        selected_chunks = chunks[chunk_offset : chunk_offset + chunk_limit]
        input_budget = _input_budget_summary(selected_chunks, max_chars_per_chunk)
        analyst = NarrativeAnalyst(_NoopProvider())
        mode_spec = analyst.get_mode_spec(mode)

        summary: dict[str, Any] = {
            "project_id": project_id,
            "mode": mode,
            "dry_run": not enable_real_llm,
            "real_llm_requested": enable_real_llm,
            "real_llm_enabled": active_settings.enable_real_llm,
            "real_llm_called": False,
            "provider_name": active_settings.llm_provider_name,
            "model": active_settings.llm_model,
            "chunk_limit": chunk_limit,
            "chunk_offset": chunk_offset,
            "max_chars_per_chunk": max_chars_per_chunk,
            "source_file_hash": checksum_text(text),
            "total_chars": len(text),
            "chapters_count": len(parsed.chapters),
            "chunks_count": len(chunks),
            "selected_chunks_count": len(selected_chunks),
            "input_chars_total": input_budget["input_chars_total"],
            "truncated_chunks_count": input_budget["truncated_chunks_count"],
            "selected_chunk_ids": [chunk.chunk_id for chunk in selected_chunks],
            "selected_chunk_ranges": [
                {
                    "chunk_id": chunk.chunk_id,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "chunk_hash": chunk.checksum,
                }
                for chunk in selected_chunks
            ],
            "import_idempotent": (
                second_import.status == "existing"
                and first_import.document.document_id == second_import.document.document_id
            ),
            "context_chunk_ids": [],
            "agent_run_status": None,
            "evidence_validation_passed": None,
            "provider_success": None,
            "output_schema": mode_spec.output_schema,
            "schema_validation_passed": None,
        }

        if not selected_chunks:
            summary["agent_run_status"] = "BLOCKED"
            summary["blocked_reason"] = "TXT file produced no selected SourceChunk records"
            _write_summary(output_dir, summary)
            return summary

        context = ContextBuilder(source_repository, max_chunks=chunk_limit).build_from_chunk_ids(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )
        summary["context_chunk_ids"] = context.source_chunk_ids

        if enable_real_llm:
            if not active_settings.enable_real_llm:
                summary["agent_run_status"] = "BLOCKED"
                summary["blocked_reason"] = "ENABLE_REAL_LLM is false"
            else:
                _run_analyst(
                    summary=summary,
                    mode=mode,
                    settings=active_settings,
                    context=context,
                    selected_chunks=selected_chunks,
                    max_chars_per_chunk=max_chars_per_chunk,
                )

        _write_summary(output_dir, summary)
        return summary
    finally:
        session.close()
        engine.dispose()


class _NoopProvider:
    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[BaseModel],
    ) -> BaseModel:
        raise RuntimeError("No provider call is available during dry-run")


def _run_analyst(
    *,
    summary: dict[str, Any],
    mode: str,
    settings: Settings,
    context: AgentContext,
    selected_chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> None:
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    try:
        provider = OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            response_format=settings.llm_response_format,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        )
        analyst = NarrativeAnalyst(provider)
        summary["real_llm_called"] = True
        visible_chunks = _visible_context_chunks(context.chunks, max_chars_per_chunk)
        proposal = analyst.run(mode, _slim_input_context(context, visible_chunks))
    except (TimeoutError, ValueError, NotImplementedError) as exc:
        summary["agent_run_status"] = "FAILED"
        summary["provider_success"] = False
        summary["schema_validation_passed"] = False
        summary["evidence_validation_passed"] = False
        summary["error_message"] = _sanitize_error_message(
            str(exc),
            settings=settings,
            selected_chunks=selected_chunks,
        )
        _add_provider_diagnostics(summary, exc)
        return

    summary["agent_run_status"] = "SUCCEEDED"
    summary["provider_success"] = True
    summary["schema_validation_passed"] = True
    _add_proposal_details(summary=summary, proposal=proposal, selected_chunks=visible_chunks)


def _visible_context_chunks(
    chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> list[SourceChunkV1]:
    return [
        chunk.model_copy(update={"text": chunk.text[:max_chars_per_chunk]})
        for chunk in chunks
    ]


def _input_budget_summary(
    chunks: list[SourceChunkV1],
    max_chars_per_chunk: int,
) -> dict[str, int]:
    return {
        "input_chars_total": sum(min(len(chunk.text), max_chars_per_chunk) for chunk in chunks),
        "truncated_chunks_count": sum(len(chunk.text) > max_chars_per_chunk for chunk in chunks),
    }


def _slim_input_context(
    context: AgentContext,
    visible_chunks: list[SourceChunkV1],
) -> dict[str, object]:
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


def _add_proposal_details(
    *,
    summary: dict[str, Any],
    proposal: BaseModel,
    selected_chunks: list[SourceChunkV1],
) -> None:
    if isinstance(proposal, EventProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["event_type"] = proposal.event_type
        summary["confidence"] = proposal.confidence
        summary.update(_validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, EntityProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["entity_type"] = proposal.entity_type
        summary["canonical_name"] = proposal.canonical_name
        summary["aliases_count"] = len(proposal.aliases)
        summary["confidence"] = proposal.confidence
        summary.update(_validate_evidence(proposal.evidence_refs, selected_chunks))
        return
    if isinstance(proposal, ClaimProposalV1):
        summary["proposal_id"] = proposal.proposal_id
        summary["claim_type"] = str(proposal.claim_type)
        summary["source_type"] = str(proposal.source_type)
        summary["verification_status"] = str(proposal.verification_status)
        summary["confidence"] = proposal.confidence
        summary.update(_validate_evidence(proposal.evidence_refs, selected_chunks))


def _validate_evidence(
    evidence_refs: list[Any],
    selected_chunks: list[SourceChunkV1],
) -> dict[str, Any]:
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


def _add_provider_diagnostics(summary: dict[str, Any], exc: BaseException) -> None:
    diagnostics = getattr(exc, "diagnostics", None)
    if not isinstance(diagnostics, dict):
        return
    summary["provider_error_diagnostics"] = diagnostics
    for key in (
        "usage_prompt_tokens",
        "usage_completion_tokens",
        "usage_total_tokens",
    ):
        if key in diagnostics:
            summary[key] = diagnostics[key]


def _sanitize_error_message(
    message: str,
    *,
    settings: Settings,
    selected_chunks: list[SourceChunkV1],
) -> str:
    sanitized = message
    if settings.llm_api_key is not None:
        secret_value = settings.llm_api_key.get_secret_value()
        if secret_value:
            sanitized = sanitized.replace(secret_value, "[redacted-secret]")
    for chunk in selected_chunks:
        if chunk.text:
            sanitized = sanitized.replace(chunk.text, "[redacted-source-text]")
    return sanitized


def _write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    path = output_dir / "narrative_analyst_smoke_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--project-id", default="narrative-analyst-smoke")
    parser.add_argument("--txt-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/evaluations"))
    parser.add_argument("--chunk-limit", type=int, default=3)
    parser.add_argument("--chunk-offset", type=int, default=0)
    parser.add_argument("--max-chars-per-chunk", type=int, default=DEFAULT_MAX_CHARS_PER_CHUNK)
    parser.add_argument("--enable-real-llm", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    settings = get_settings()
    updates: dict[str, Any] = {}
    if args.model is not None:
        updates["llm_model"] = args.model
    if args.base_url is not None:
        updates["llm_base_url"] = args.base_url
    if updates:
        settings = settings.model_copy(update=updates)

    summary = run_smoke(
        mode=args.mode,
        project_id=args.project_id,
        txt_path=args.txt_path,
        output_dir=args.output_dir,
        chunk_limit=args.chunk_limit,
        chunk_offset=args.chunk_offset,
        max_chars_per_chunk=args.max_chars_per_chunk,
        enable_real_llm=args.enable_real_llm,
        settings=settings,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
