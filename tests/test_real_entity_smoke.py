import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from comic_agent.config import Settings
from scripts.smoke_real_entity_agent import run_smoke

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def test_smoke_real_entity_agent_dry_run_does_not_call_real_llm(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text(
        "First demo paragraph.\n\nSecond demo paragraph.",
        encoding="utf-8",
    )

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=2,
        enable_real_llm=False,
        settings=Settings(_env_file=None, llm_api_key="secret-test-key"),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["dry_run"] is True
    assert summary["real_llm_called"] is False
    assert summary["selected_chunks_count"] == 2
    assert summary["context_chunk_ids"] == summary["selected_chunk_ids"]
    assert summary["import_idempotent"] is True
    assert "First demo paragraph" not in serialized
    assert "Second demo paragraph" not in serialized
    assert "secret-test-key" not in serialized
    assert "key_status" not in summary
    assert (tmp_path / "out" / "real_entity_agent_smoke_summary.json").exists()


def test_smoke_real_entity_agent_real_flag_requires_env_enable(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("Alpha opens the blue gate.", encoding="utf-8")

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
    assert summary["agent_run_status"] == "BLOCKED"
    assert summary["blocked_reason"] == "ENABLE_REAL_LLM is false"


class FakeSuccessfulProvider:
    def __init__(self, **_: Any) -> None:
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.requests.append(request)
        input_context = request["input_context"]
        assert isinstance(input_context, dict)
        source_chunks = input_context["source_chunks"]
        assert isinstance(source_chunks, list)
        source_chunk = source_chunks[0]
        assert isinstance(source_chunk, dict)
        assert set(source_chunk) == {
            "chunk_id",
            "chapter_id",
            "char_start",
            "char_end",
            "text",
        }
        quote_text = str(source_chunk["text"])[:5]
        return output_model.model_validate(
            {
                "proposal_id": "entity-smoke-1",
                "entity_type": "CHARACTER",
                "canonical_name": "Demo Entity",
                "aliases": ["Demo Alias", "Entity Alias"],
                "evidence_refs": [
                    {
                        "chunk_id": source_chunk["chunk_id"],
                        "quote_start": 0,
                        "quote_end": len(quote_text),
                        "quote_text": quote_text,
                    }
                ],
                "confidence": 0.83,
            }
        )


def test_smoke_real_entity_agent_summary_includes_sanitized_success_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("Alpha opens the blue gate.", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_real_entity_agent.OpenAICompatibleLLMProvider",
        FakeSuccessfulProvider,
    )

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        enable_real_llm=True,
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            llm_api_key="secret-test-key",
        ),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["real_llm_called"] is True
    assert summary["agent_run_status"] == "SUCCEEDED"
    assert summary["provider_success"] is True
    assert summary["output_schema"] == "EntityProposalV1"
    assert summary["schema_validation_passed"] is True
    assert summary["evidence_validation_passed"] is True
    assert summary["proposal_id"] == "entity-smoke-1"
    assert summary["entity_type"] == "CHARACTER"
    assert summary["canonical_name"] == "Demo Entity"
    assert summary["aliases_count"] == 2
    assert summary["evidence_chunk_id"] == summary["selected_chunk_ids"][0]
    assert summary["quote_matched"] is True
    assert summary["char_range_matched"] is True
    assert "Alpha opens the blue gate" not in serialized
    assert "Alpha" not in serialized
    assert "secret-test-key" not in serialized
    assert "message.content" not in serialized


class FakeFailedProvider:
    def __init__(self, **_: Any) -> None:
        pass

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        raise ValueError("LLM provider response content is missing")


def test_smoke_real_entity_agent_summary_includes_sanitized_failure_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("Alpha opens the blue gate.", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_real_entity_agent.OpenAICompatibleLLMProvider",
        FakeFailedProvider,
    )

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        enable_real_llm=True,
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            llm_api_key="secret-test-key",
        ),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["real_llm_called"] is True
    assert summary["agent_run_status"] == "FAILED"
    assert summary["provider_success"] is False
    assert summary["schema_validation_passed"] is False
    assert summary["evidence_validation_passed"] is False
    assert summary["error_message"] == "LLM provider response content is missing"
    assert "Alpha opens the blue gate" not in serialized
    assert "Alpha" not in serialized
    assert "secret-test-key" not in serialized
    assert "message.content" not in serialized
