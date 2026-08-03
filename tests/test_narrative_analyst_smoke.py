import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from comic_agent.config import Settings
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import ClaimProposalV1, EntityProposalV1, EventProposalV1
from scripts.smoke_narrative_analyst import DEFAULT_MAX_CHARS_PER_CHUNK, run_smoke

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def test_smoke_narrative_analyst_dry_run_does_not_call_real_llm(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("First secret paragraph.\n\nSecond secret paragraph.", encoding="utf-8")

    summary = run_smoke(
        mode="claim_extraction",
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=2,
        chunk_offset=0,
        enable_real_llm=False,
        settings=Settings(_env_file=None, llm_api_key="secret-test-key"),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["mode"] == "claim_extraction"
    assert summary["dry_run"] is True
    assert summary["real_llm_called"] is False
    assert summary["selected_chunks_count"] == 2
    assert summary["context_chunk_ids"] == summary["selected_chunk_ids"]
    assert summary["output_schema"] == "ClaimProposalV1"
    assert summary["chunk_limit"] == 2
    assert summary["chunk_offset"] == 0
    assert summary["max_chars_per_chunk"] == DEFAULT_MAX_CHARS_PER_CHUNK
    assert summary["input_chars_total"] == len("First secret paragraph.") + len(
        "Second secret paragraph."
    )
    assert summary["truncated_chunks_count"] == 0
    assert "First secret paragraph" not in serialized
    assert "Second secret paragraph" not in serialized
    assert "secret-test-key" not in serialized
    assert "message.content" not in serialized
    assert (tmp_path / "out" / "narrative_analyst_smoke_summary.json").exists()


def test_smoke_narrative_analyst_dry_run_applies_input_budget_to_summary(
    tmp_path: Path,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("A" * 50 + "\n\n" + "B" * 30, encoding="utf-8")

    summary = run_smoke(
        mode="event_extraction",
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=2,
        chunk_offset=0,
        max_chars_per_chunk=10,
        enable_real_llm=False,
        settings=Settings(_env_file=None, llm_api_key="secret-test-key"),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["real_llm_called"] is False
    assert summary["max_chars_per_chunk"] == 10
    assert summary["input_chars_total"] == 20
    assert summary["truncated_chunks_count"] == 2
    assert "A" * 11 not in serialized
    assert "B" * 11 not in serialized


def test_smoke_narrative_analyst_real_flag_requires_env_enable(tmp_path: Path) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("The witness claimed the door was locked.", encoding="utf-8")

    summary = run_smoke(
        mode="claim_extraction",
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=1,
        chunk_offset=0,
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
    seen_text_lengths: list[int] = []

    def __init__(self, **_: Any) -> None:
        pass

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
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
        assert len(str(source_chunk["text"])) <= 10
        self.seen_text_lengths.append(len(str(source_chunk["text"])))
        quote_text = str(source_chunk["text"])[:7]
        if output_model is EventProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "event-smoke-1",
                    "event_type": "claim",
                    "summary": "A concise event.",
                    "participant_ids": [],
                    "actor_resolution_status": "UNKNOWN",
                    "location_id": None,
                    "evidence_refs": [{"chunk_id": source_chunk["chunk_id"]}],
                    "confidence": 0.7,
                    "reality_layer": "PRIMARY",
                }
            )
        if output_model is EntityProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "entity-smoke-1",
                    "entity_type": "CHARACTER",
                    "canonical_name": "Demo Entity",
                    "aliases": [],
                    "evidence_refs": [{"chunk_id": source_chunk["chunk_id"]}],
                    "confidence": 0.7,
                }
            )
        if output_model is ClaimProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "claim-smoke-1",
                    "claim_type": "ASSERTION",
                    "claim_text": "The witness claimed the door was locked.",
                    "source_type": "CHARACTER",
                    "source_id": None,
                    "target_event_id": None,
                    "verification_status": "UNVERIFIED",
                    "evidence_refs": [
                        {
                            "chunk_id": source_chunk["chunk_id"],
                            "quote_start": 0,
                            "quote_end": len(quote_text),
                            "quote_text": quote_text,
                        }
                    ],
                    "confidence": 0.84,
                    "reality_layer": "PRIMARY",
                }
            )
        raise AssertionError(f"Unexpected output model: {output_model}")


def test_smoke_narrative_analyst_claim_success_summary_is_sanitized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("The witness claimed the door was locked.", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_narrative_analyst.OpenAICompatibleLLMProvider",
        FakeSuccessfulProvider,
    )
    FakeSuccessfulProvider.seen_text_lengths = []

    summary = run_smoke(
        mode="claim_extraction",
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=1,
        chunk_offset=0,
        max_chars_per_chunk=10,
        enable_real_llm=True,
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            llm_api_key="secret-test-key",
        ),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["mode"] == "claim_extraction"
    assert summary["real_llm_called"] is True
    assert summary["max_chars_per_chunk"] == 10
    assert summary["input_chars_total"] == 10
    assert summary["truncated_chunks_count"] == 1
    assert summary["agent_run_status"] == "SUCCEEDED"
    assert summary["provider_success"] is True
    assert summary["schema_validation_passed"] is True
    assert summary["evidence_validation_passed"] is True
    assert summary["proposal_id"] == "claim-smoke-1"
    assert summary["claim_type"] == "ASSERTION"
    assert summary["source_type"] == "CHARACTER"
    assert summary["verification_status"] == "UNVERIFIED"
    assert summary["confidence"] == 0.84
    assert summary["evidence_chunk_id"] == summary["selected_chunk_ids"][0]
    assert summary["quote_matched"] is True
    assert summary["char_range_matched"] is True
    assert "The witness claimed the door was locked" not in serialized
    assert "The wit" not in serialized
    assert "secret-test-key" not in serialized
    assert "message.content" not in serialized
    assert FakeSuccessfulProvider.seen_text_lengths == [10]


def test_smoke_narrative_analyst_input_budget_does_not_modify_source_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_text = "The witness claimed the door was locked."
    txt_path = tmp_path / "source.txt"
    txt_path.write_text(original_text, encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_narrative_analyst.OpenAICompatibleLLMProvider",
        FakeSuccessfulProvider,
    )

    summary = run_smoke(
        mode="claim_extraction",
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=1,
        chunk_offset=0,
        max_chars_per_chunk=10,
        enable_real_llm=True,
        settings=Settings(
            _env_file=None,
            enable_real_llm=True,
            llm_api_key="secret-test-key",
        ),
    )

    sqlite_path = tmp_path / "out" / "narrative_analyst_smoke.sqlite"
    engine = make_engine(f"sqlite+pysqlite:///{sqlite_path}")
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        source_repository = SourceRepository(session)
        chunk = source_repository.get_chunk(summary["selected_chunk_ids"][0])
        assert chunk is not None
        assert chunk.text == original_text
    finally:
        session.close()
        engine.dispose()


def test_smoke_narrative_analyst_input_budget_applies_to_all_implemented_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("The witness claimed the door was locked.", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_narrative_analyst.OpenAICompatibleLLMProvider",
        FakeSuccessfulProvider,
    )

    for mode in ("event_extraction", "entity_extraction", "claim_extraction"):
        FakeSuccessfulProvider.seen_text_lengths = []
        summary = run_smoke(
            mode=mode,
            project_id=f"project-{mode}",
            txt_path=txt_path,
            output_dir=tmp_path / mode,
            chunk_limit=1,
            chunk_offset=0,
            max_chars_per_chunk=10,
            enable_real_llm=True,
            settings=Settings(
                _env_file=None,
                enable_real_llm=True,
                llm_api_key="secret-test-key",
            ),
        )

        assert summary["mode"] == mode
        assert summary["input_chars_total"] == 10
        assert summary["truncated_chunks_count"] == 1
        assert FakeSuccessfulProvider.seen_text_lengths == [10]
