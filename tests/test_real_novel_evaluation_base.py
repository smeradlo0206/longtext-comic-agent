import json
from hashlib import sha256
from pathlib import Path

from scripts.evaluate_real_novel_base import run_real_novel_base_evaluation


def test_real_novel_base_evaluation_writes_sanitized_summary(tmp_path: Path) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    metadata_path = tmp_path / "novel_metadata.json"
    secret_sentence = "Captain Vale crossed the red valley before dawn."
    txt_path.write_text(
        "\n\n".join(
            [
                "Chapter 1 Arrival",
                secret_sentence,
                "Mara lifted the bronze flag and called the riders.",
                "Chapter 2 Rescue",
                "The scouts found a wounded envoy near the gate.",
            ]
        ),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "source_type": "public_domain",
                "title": "Synthetic Public Domain Style Sample",
                "author": "Test Suite",
                "source_url": "https://example.test/public-domain",
                "license_status": "Public domain test fixture",
                "text_sha256": "not-the-current-hash",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_real_novel_base_evaluation(
        project_id="project-1",
        txt_path=txt_path,
        metadata_path=metadata_path,
        output_dir=tmp_path / "out",
        context_chunk_limit=2,
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["real_llm_called"] is False
    assert summary["source_type"] == "public_domain"
    assert summary["title"] == "Synthetic Public Domain Style Sample"
    assert summary["chapters_count"] == 2
    assert summary["chunks_count"] == 3
    assert summary["average_chunk_length"] > 0
    assert summary["import_idempotent"] is True
    assert summary["context_builder_passed"] is True
    assert summary["selected_chunks_count"] == 2
    assert summary["text_sha256_matches_metadata"] is False
    assert summary["agent_run_saved"] is False
    assert secret_sentence not in serialized
    assert "Mara lifted" not in serialized
    assert (tmp_path / "out" / "real_novel_base_summary.json").exists()
    assert (tmp_path / "out" / "real_novel_base_summary.md").exists()


def test_real_novel_base_evaluation_handles_empty_chunk_selection(tmp_path: Path) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    metadata_path = tmp_path / "novel_metadata.json"
    txt_path.write_text("   \n\n", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    summary = run_real_novel_base_evaluation(
        project_id="project-1",
        txt_path=txt_path,
        metadata_path=metadata_path,
        output_dir=tmp_path / "out",
    )

    assert summary["chapters_count"] == 1
    assert summary["chunks_count"] == 0
    assert summary["average_chunk_length"] == 0
    assert summary["context_builder_passed"] is False
    assert summary["blocked_reason"] == "TXT file produced no SourceChunk records"


def test_real_novel_base_evaluation_accepts_metadata_with_utf8_bom(tmp_path: Path) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    metadata_path = tmp_path / "novel_metadata.json"
    txt_path.write_text("Chapter 1 Arrival\n\nA courier entered the hall.", encoding="utf-8")
    metadata_path.write_text(
        "\ufeff" + json.dumps({"title": "BOM Metadata Sample"}),
        encoding="utf-8",
    )

    summary = run_real_novel_base_evaluation(
        project_id="project-1",
        txt_path=txt_path,
        metadata_path=metadata_path,
        output_dir=tmp_path / "out",
    )

    assert summary["title"] == "BOM Metadata Sample"


def test_real_novel_base_evaluation_uses_raw_file_sha256_for_metadata_match(
    tmp_path: Path,
) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    metadata_path = tmp_path / "novel_metadata.json"
    raw_text = "\ufeffChapter 1 Arrival\r\n\r\nA courier entered the hall.".encode("utf-8")
    expected_hash = sha256(raw_text).hexdigest()
    txt_path.write_bytes(raw_text)
    metadata_path.write_text(
        json.dumps({"text_sha256": expected_hash}),
        encoding="utf-8",
    )

    summary = run_real_novel_base_evaluation(
        project_id="project-1",
        txt_path=txt_path,
        metadata_path=metadata_path,
        output_dir=tmp_path / "out",
    )

    assert summary["source_file_hash"] == expected_hash
    assert summary["text_sha256_matches_metadata"] is True
