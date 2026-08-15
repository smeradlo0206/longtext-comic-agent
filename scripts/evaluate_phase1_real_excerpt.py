"""Run a local, sanitized phase-one evaluation over a TXT excerpt."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import RealityLayer
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text
from comic_agent.workflows.mock_event_workflow import MockEventWorkflow


def run_evaluation(
    project_id: str,
    txt_path: Path,
    output_dir: Path,
    source_url: str | None = None,
    title: str | None = None,
    author: str | None = None,
    license_status: str | None = None,
    text_source_type: str = "user_provided",
) -> dict[str, Any]:
    """Evaluate the phase-one mock audit loop without exposing source text."""

    text = txt_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "phase1_real_eval.sqlite"
    engine = make_engine(f"sqlite+pysqlite:///{db_path}")
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
        document_chunks = source_repository.list_document_chunks(first_import.document.document_id)
        selected_chunks = document_chunks[: min(3, len(document_chunks))]
        if not selected_chunks:
            raise ValueError("Evaluation text produced no SourceChunk records")

        quote_text = _short_internal_quote(selected_chunks[0].text)
        success_response = _event_response(selected_chunks[0].chunk_id, quote_text)
        workflow = MockEventWorkflow(
            source_repository=source_repository,
            agent_run_repository=agent_run_repository,
            provider=MockLLMProvider(response=success_response),
        )
        first_run = workflow.run(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )
        count_after_first_run = agent_run_repository.count_agent_runs()
        second_run = workflow.run(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )
        count_after_second_run = agent_run_repository.count_agent_runs()

        failed_workflow = MockEventWorkflow(
            source_repository=source_repository,
            agent_run_repository=agent_run_repository,
            provider=MockLLMProvider(
                response=_event_response(
                    selected_chunks[0].chunk_id,
                    quote_text="phase-one-evidence-miss",
                )
            ),
        )
        failed_run = failed_workflow.run(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )

        summary: dict[str, Any] = {
            "project_id": project_id,
            "text_source_type": text_source_type,
            "source_url": source_url,
            "title": title,
            "author": author,
            "license_status": license_status,
            "source_file_hash": checksum_text(text),
            "total_chars": len(text),
            "chapters_count": len(parsed.chapters),
            "chunks_count": len(document_chunks),
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
            "evidence_quote_hash": checksum_text(quote_text),
            "evidence_validation_passed": (
                first_run.agent_run.payload["evidence_validation_passed"] is True
            ),
            "agent_run_saved": (
                agent_run_repository.get_agent_run(first_run.agent_run.agent_run_id) is not None
            ),
            "agent_run_id": first_run.agent_run.agent_run_id,
            "import_idempotent": (
                second_import.status == "existing"
                and first_import.document.document_id == second_import.document.document_id
                and len(document_chunks) == len(parsed.chunks)
            ),
            "run_idempotent": (
                first_run.agent_run.agent_run_id == second_run.agent_run.agent_run_id
                and count_after_first_run == count_after_second_run
            ),
            "failed_case_recorded": (
                failed_run.agent_run.status == "FAILED"
                and agent_run_repository.get_agent_run(failed_run.agent_run.agent_run_id)
                is not None
            ),
            "failed_agent_run_id": failed_run.agent_run.agent_run_id,
        }
        _write_summary_files(output_dir, summary)
        return summary
    finally:
        session.close()
        engine.dispose()


def _event_response(chunk_id: str, quote_text: str) -> dict[str, object]:
    return {
        "proposal_id": stable_proposal_id(chunk_id, quote_text),
        "event_type": "mock_excerpt_event",
        "summary": "Mock event extracted from a selected source chunk.",
        "participant_ids": [],
        "actor_resolution_status": "UNKNOWN",
        "location_id": None,
        "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote_text}],
        "confidence": 0.8,
        "reality_layer": RealityLayer.PRIMARY,
    }


def stable_proposal_id(chunk_id: str, quote_text: str) -> str:
    """Return a deterministic proposal id without embedding source text."""

    return f"proposal_{checksum_text(f'{chunk_id}:{quote_text}')[:16]}"


def _short_internal_quote(text: str) -> str:
    compact = text.strip()
    return compact[: min(8, len(compact))]


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> None:
    json_path = output_dir / "phase1_evaluation_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_dir / "phase1_evaluation_summary.md"
    md_path.write_text(_summary_markdown(summary), encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 Evaluation Summary",
        "",
        f"- text_source_type: {summary['text_source_type']}",
        f"- source_url: {summary['source_url']}",
        f"- title: {summary['title']}",
        f"- author: {summary['author']}",
        f"- license_status: {summary['license_status']}",
        f"- source_file_hash: {summary['source_file_hash']}",
        f"- total_chars: {summary['total_chars']}",
        f"- chapters_count: {summary['chapters_count']}",
        f"- chunks_count: {summary['chunks_count']}",
        f"- selected_chunks_count: {summary['selected_chunks_count']}",
        f"- evidence_validation_passed: {summary['evidence_validation_passed']}",
        f"- agent_run_saved: {summary['agent_run_saved']}",
        f"- import_idempotent: {summary['import_idempotent']}",
        f"- run_idempotent: {summary['run_idempotent']}",
        f"- failed_case_recorded: {summary['failed_case_recorded']}",
        "",
        "Selected chunk metadata:",
    ]
    for item in summary["selected_chunk_ranges"]:
        lines.append(
            "- "
            f"chunk_id={item['chunk_id']}, "
            f"char_start={item['char_start']}, "
            f"char_end={item['char_end']}, "
            f"chunk_hash={item['chunk_hash']}"
        )
    lines.append("")
    lines.append("No source excerpt text or full quote is included in this summary.")
    return "\n".join(lines)


def main() -> None:
    """CLI entry point for local real excerpt evaluation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="phase1-real-eval")
    parser.add_argument("--txt-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/evaluations"))
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--author", default=None)
    parser.add_argument("--license-status", default=None)
    parser.add_argument("--text-source-type", default="user_provided")
    args = parser.parse_args()

    summary = run_evaluation(
        project_id=args.project_id,
        txt_path=args.txt_path,
        output_dir=args.output_dir,
        source_url=args.source_url,
        title=args.title,
        author=args.author,
        license_status=args.license_status,
        text_source_type=args.text_source_type,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
