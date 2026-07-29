import json
import subprocess
import sys
from pathlib import Path

from scripts.evaluate_phase1_real_excerpt import run_evaluation


def test_phase1_real_excerpt_evaluation_writes_sanitized_summary(tmp_path: Path) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    txt_path.write_text(
        "Chapter 1 Down the Corridor\n\n"
        "Alice saw the rabbit hurry past the door.\n\n"
        "She followed him and wondered what would happen next.\n\n"
        "Chapter 2 The Small Room\n\n"
        "The key lay on the glass table.\n\n"
        "Alice reached for it before the door closed.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "evaluations"

    summary = run_evaluation(
        project_id="phase1-real-eval",
        txt_path=txt_path,
        output_dir=output_dir,
        source_url="https://www.gutenberg.org/ebooks/11",
        title="Alice's Adventures in Wonderland",
        author="Lewis Carroll",
        license_status="Public domain in the USA",
        text_source_type="public_domain",
    )

    assert summary["chapters_count"] == 2
    assert summary["chunks_count"] == 4
    assert summary["selected_chunks_count"] > 0
    assert summary["evidence_validation_passed"] is True
    assert summary["agent_run_saved"] is True
    assert summary["import_idempotent"] is True
    assert summary["run_idempotent"] is True
    assert summary["failed_case_recorded"] is True
    assert "source_excerpt" not in summary
    assert "quote_text" not in json.dumps(summary, ensure_ascii=False)
    assert (output_dir / "phase1_evaluation_summary.json").exists()
    assert (output_dir / "phase1_evaluation_summary.md").exists()


def test_phase1_real_excerpt_evaluation_cli_runs_from_repo_root(tmp_path: Path) -> None:
    txt_path = tmp_path / "novel_excerpt.txt"
    txt_path.write_text(
        "Chapter 1 Start\n\nAlice opened the door.\n\nThe rabbit hurried away.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "evaluations"
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "evaluate_phase1_real_excerpt.py"),
            "--project-id",
            "phase1-real-eval",
            "--txt-path",
            str(txt_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    summary = json.loads(result.stdout)
    assert summary["agent_run_saved"] is True
    assert "quote_text" not in result.stdout
