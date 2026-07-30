import json
from pathlib import Path

from comic_agent.config import Settings
from scripts.smoke_real_event_agent import run_smoke


def test_smoke_real_event_agent_dry_run_does_not_call_real_llm(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("第一章 开端\n\n林夏推开门。", encoding="utf-8")

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        enable_real_llm=False,
        settings=Settings(_env_file=None, llm_api_key="secret-test-key"),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["dry_run"] is True
    assert summary["real_llm_called"] is False
    assert summary["chapters_count"] == 1
    assert summary["chunks_count"] == 1
    assert summary["selected_chunks_count"] == 1
    assert summary["import_idempotent"] is True
    assert summary["key_status"] == {
        "configured": True,
        "length": len("secret-test-key"),
        "looks_like_key": False,
    }
    assert "secret-test-key" not in serialized
    assert "林夏推开门" not in serialized
    assert (tmp_path / "out" / "real_event_agent_smoke_summary.json").exists()


def test_smoke_real_event_agent_real_flag_requires_env_enable(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("第一章 开端\n\n林夏推开门。", encoding="utf-8")

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        enable_real_llm=True,
        settings=Settings(
            _env_file=None,
            enable_real_llm=False,
            llm_api_key="sk-placeholder",
        ),
    )

    assert summary["real_llm_requested"] is True
    assert summary["real_llm_enabled"] is False
    assert summary["real_llm_called"] is False
    assert summary["blocked_reason"] == "ENABLE_REAL_LLM is false"
