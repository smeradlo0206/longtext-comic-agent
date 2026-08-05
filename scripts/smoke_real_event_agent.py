"""Dry-run or explicitly run the minimal real Event agent workflow."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.config import Settings, get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import EventProposalBatchV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import AgentRunV1
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_analyst_summary import add_proposal_details
from comic_agent.workflows.real_event_workflow import RealEventWorkflow


def run_smoke(
    *,
    project_id: str,
    txt_path: Path,
    output_dir: Path,
    chunk_limit: int = 3,
    enable_real_llm: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run a sanitized smoke check without exposing source text or secrets."""

    if chunk_limit < 1:
        raise ValueError("chunk_limit must be at least 1")

    active_settings = settings or get_settings()
    text = txt_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(f"sqlite+pysqlite:///{output_dir / 'real_event_smoke.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    session: Session = session_factory()
    try:
        source_repository = SourceRepository(session)
        agent_run_repository = AgentRunRepository(session)
        parsed = DocumentParser().parse_txt(
            project_id=project_id,
            filename=txt_path.name,
            text=text,
            storage_uri=f"local://{txt_path.name}",
        )
        first_import = source_repository.import_parsed_document(parsed)
        second_import = source_repository.import_parsed_document(parsed)
        chunks = source_repository.list_document_chunks(first_import.document.document_id)
        selected_chunks = chunks[: min(chunk_limit, len(chunks))]

        summary: dict[str, Any] = {
            "project_id": project_id,
            "dry_run": not enable_real_llm,
            "real_llm_requested": enable_real_llm,
            "real_llm_enabled": active_settings.enable_real_llm,
            "real_llm_called": False,
            "provider_name": active_settings.llm_provider_name,
            "model": active_settings.llm_model,
            "source_file_hash": checksum_text(text),
            "total_chars": len(text),
            "chapters_count": len(parsed.chapters),
            "chunks_count": len(chunks),
            "selected_chunks_count": len(selected_chunks),
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
            "agent_run_saved": False,
            "agent_run_id": None,
            "agent_run_status": None,
            "evidence_validation_passed": None,
        }
        if not selected_chunks:
            summary["blocked_reason"] = "TXT file produced no SourceChunk records"
            _write_summary(output_dir, summary)
            return summary

        context = ContextBuilder(source_repository, max_chunks=chunk_limit).build_from_chunk_ids(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )
        summary["context_chunk_ids"] = context.source_chunk_ids

        if enable_real_llm:
            if not active_settings.enable_real_llm:
                summary["blocked_reason"] = "ENABLE_REAL_LLM is false"
            else:
                workflow = RealEventWorkflow(
                    settings=active_settings,
                    source_repository=source_repository,
                    agent_run_repository=agent_run_repository,
                )
                result = workflow.run(project_id, context.source_chunk_ids)
                summary["real_llm_called"] = True
                summary["agent_run_saved"] = (
                    agent_run_repository.get_agent_run(result.agent_run.agent_run_id) is not None
                )
                summary["agent_run_id"] = result.agent_run.agent_run_id
                summary["agent_run_status"] = str(result.agent_run.status)
                summary["evidence_validation_passed"] = result.agent_run.payload.get(
                    "evidence_validation_passed"
                )
                summary["error_message"] = result.agent_run.error_message
                _add_agent_run_details(
                    summary=summary,
                    agent_run=result.agent_run,
                    proposal=result.proposal,
                    selected_chunks=selected_chunks,
                )

        _write_summary(output_dir, summary)
        return summary
    finally:
        session.close()
        engine.dispose()


def _add_agent_run_details(
    *,
    summary: dict[str, Any],
    agent_run: AgentRunV1,
    proposal: EventProposalBatchV1 | None,
    selected_chunks: list[SourceChunkV1],
) -> None:
    provider_result = agent_run.provider_result
    if provider_result is not None:
        summary["provider_result_id"] = provider_result.provider_result_id
        summary["provider_success"] = provider_result.success
    diagnostics = agent_run.payload.get("provider_error_diagnostics")
    if isinstance(diagnostics, dict):
        summary["provider_error_diagnostics"] = diagnostics
        for key in (
            "usage_prompt_tokens",
            "usage_completion_tokens",
            "usage_total_tokens",
        ):
            if key in diagnostics:
                summary[key] = diagnostics[key]

    summary["output_schema"] = agent_run.output_schema
    summary["schema_validation_passed"] = proposal is not None
    if proposal is None:
        return

    add_proposal_details(summary=summary, proposal=proposal, selected_chunks=selected_chunks)


def _write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    path = output_dir / "real_event_agent_smoke_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="real-event-smoke")
    parser.add_argument("--txt-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/evaluations"))
    parser.add_argument("--chunk-limit", type=int, default=3)
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
        project_id=args.project_id,
        txt_path=args.txt_path,
        output_dir=args.output_dir,
        chunk_limit=args.chunk_limit,
        enable_real_llm=args.enable_real_llm,
        settings=settings,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
