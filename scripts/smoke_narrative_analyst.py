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
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_analyst_summary import (
    DEFAULT_MAX_CHARS_PER_CHUNK,
    add_proposal_details,
    add_provider_diagnostics,
    base_eval_summary,
    classify_evidence_result,
    classify_exception,
    sanitize_error_message,
    set_failure,
    slim_input_context,
    visible_context_chunks,
)


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
        analyst = NarrativeAnalyst(_NoopProvider())
        mode_spec = analyst.get_mode_spec(mode)

        summary = base_eval_summary(
            project_id=project_id,
            mode=mode,
            real_llm_requested=enable_real_llm,
            real_llm_enabled=active_settings.enable_real_llm,
            provider_name=active_settings.llm_provider_name,
            model=active_settings.llm_model,
            chunk_limit=chunk_limit,
            chunk_offset=chunk_offset,
            max_chars_per_chunk=max_chars_per_chunk,
            selected_chunks=selected_chunks,
            output_schema=mode_spec.output_schema,
            import_idempotent=(
                second_import.status == "existing"
                and first_import.document.document_id == second_import.document.document_id
            ),
        )
        summary.update(
            {
                "source_file_hash": checksum_text(text),
                "total_chars": len(text),
                "chapters_count": len(parsed.chapters),
                "chunks_count": len(chunks),
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
            }
        )

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
        visible_chunks = visible_context_chunks(context.chunks, max_chars_per_chunk)
        proposal = analyst.run(mode, slim_input_context(context, visible_chunks))
    except (TimeoutError, ValueError, NotImplementedError) as exc:
        summary["agent_run_status"] = "FAILED"
        summary["provider_success"] = False
        summary["schema_validation_passed"] = False
        summary["evidence_validation_passed"] = False
        summary["error_message"] = sanitize_error_message(
            str(exc),
            settings=settings,
            selected_chunks=selected_chunks,
        )
        add_provider_diagnostics(summary, exc)
        set_failure(summary, classify_exception(exc))
        return
    except Exception as exc:
        summary["agent_run_status"] = "FAILED"
        summary["provider_success"] = False
        summary["schema_validation_passed"] = False
        summary["evidence_validation_passed"] = False
        summary["error_message"] = sanitize_error_message(
            str(exc),
            settings=settings,
            selected_chunks=selected_chunks,
        )
        set_failure(summary, "UNKNOWN_ERROR")
        return

    summary["agent_run_status"] = "SUCCEEDED"
    summary["provider_success"] = True
    summary["schema_validation_passed"] = True
    add_proposal_details(summary=summary, proposal=proposal, selected_chunks=visible_chunks)
    classify_evidence_result(summary)


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
