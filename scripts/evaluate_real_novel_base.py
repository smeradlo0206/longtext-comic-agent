"""Build a sanitized local evaluation baseline for a real TXT novel."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_bytes


def run_real_novel_base_evaluation(
    *,
    project_id: str,
    txt_path: Path,
    metadata_path: Path,
    output_dir: Path,
    context_chunk_limit: int = 3,
) -> dict[str, Any]:
    """Import a real local novel TXT and write a sanitized dry-run summary."""

    if context_chunk_limit < 1:
        raise ValueError("context_chunk_limit must be at least 1")

    raw_data = txt_path.read_bytes()
    text = raw_data.decode("utf-8")
    metadata = _read_metadata(metadata_path)
    text_sha256 = checksum_bytes(raw_data)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine("sqlite+pysqlite:///:memory:")
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
        selected_chunks = chunks[: min(context_chunk_limit, len(chunks))]

        summary: dict[str, Any] = {
            "project_id": project_id,
            "real_llm_called": False,
            "source_type": metadata.get("source_type"),
            "title": metadata.get("title"),
            "author": metadata.get("author"),
            "source_url": metadata.get("source_url"),
            "license_status": metadata.get("license_status"),
            "selected_reason": metadata.get("selected_reason"),
            "source_file_hash": text_sha256,
            "metadata_text_sha256": metadata.get("text_sha256"),
            "text_sha256_matches_metadata": metadata.get("text_sha256") == text_sha256,
            "total_chars": len(text),
            "chapters_count": len(parsed.chapters),
            "chunks_count": len(chunks),
            "average_chunk_length": _average_chunk_length(chunks),
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
                and len(chunks) == len(parsed.chunks)
            ),
            "context_builder_passed": False,
            "context_chunk_ids": [],
            "agent_run_saved": False,
            "provider_result_saved": False,
        }

        if not selected_chunks:
            summary["blocked_reason"] = "TXT file produced no SourceChunk records"
            _write_summary_files(output_dir, summary)
            return summary

        context = ContextBuilder(
            source_repository,
            max_chunks=context_chunk_limit,
        ).build_from_chunk_ids(
            project_id=project_id,
            chunk_ids=[chunk.chunk_id for chunk in selected_chunks],
        )
        summary["context_builder_passed"] = True
        summary["context_chunk_ids"] = context.source_chunk_ids

        _write_summary_files(output_dir, summary)
        return summary
    finally:
        session.close()
        engine.dispose()


def _read_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8-sig"))


def _average_chunk_length(chunks: list[Any]) -> int:
    if not chunks:
        return 0
    return round(sum(len(chunk.text) for chunk in chunks) / len(chunks))


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> None:
    json_path = output_dir / "real_novel_base_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_dir / "real_novel_base_summary.md"
    md_path.write_text(_summary_markdown(summary), encoding="utf-8")


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Real Novel Base Evaluation Summary",
        "",
        "This summary is sanitized. It contains no novel正文, long quote, or API key.",
        "",
        f"- source_type: {summary['source_type']}",
        f"- title: {summary['title']}",
        f"- author: {summary['author']}",
        f"- source_url: {summary['source_url']}",
        f"- license_status: {summary['license_status']}",
        f"- source_file_hash: {summary['source_file_hash']}",
        f"- total_chars: {summary['total_chars']}",
        f"- chapters_count: {summary['chapters_count']}",
        f"- chunks_count: {summary['chunks_count']}",
        f"- average_chunk_length: {summary['average_chunk_length']}",
        f"- selected_chunks_count: {summary['selected_chunks_count']}",
        f"- import_idempotent: {summary['import_idempotent']}",
        f"- context_builder_passed: {summary['context_builder_passed']}",
        f"- real_llm_called: {summary['real_llm_called']}",
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
    if "blocked_reason" in summary:
        lines.extend(["", f"blocked_reason: {summary['blocked_reason']}"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """CLI entry point for local real novel dry-run evaluation."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="real-novel-base")
    parser.add_argument("--txt-path", type=Path, default=Path("local_eval/novel_excerpt.txt"))
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=Path("local_eval/novel_metadata.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/evaluations"))
    parser.add_argument("--context-chunk-limit", type=int, default=3)
    args = parser.parse_args()

    summary = run_real_novel_base_evaluation(
        project_id=args.project_id,
        txt_path=args.txt_path,
        metadata_path=args.metadata_path,
        output_dir=args.output_dir,
        context_chunk_limit=args.context_chunk_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
