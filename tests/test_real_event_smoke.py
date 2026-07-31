import json
from pathlib import Path
from typing import Any

from comic_agent.config import Settings
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import ActorResolutionStatus, EventProposalV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1, ProviderResultV1, ProviderType
from comic_agent.workflows.real_event_workflow import DETERMINISTIC_REAL_AUDIT_TIME
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


class FakeSuccessfulWorkflow:
    def __init__(self, **kwargs: Any) -> None:
        self.source_repository = kwargs["source_repository"]

    def run(self, project_id: str, chunk_ids: list[str]):
        chunk = self.source_repository.get_chunk(chunk_ids[0])
        assert chunk is not None
        quote_text = chunk.text[:3]
        proposal = EventProposalV1(
            proposal_id="proposal-smoke-1",
            event_type="discovery",
            summary="summary without source text",
            participant_ids=["char-lin"],
            actor_resolution_status=ActorResolutionStatus.KNOWN,
            location_id=None,
            evidence_refs=[
                EvidenceRefV1(
                    chunk_id=chunk.chunk_id,
                    quote_start=0,
                    quote_end=len(quote_text),
                    quote_text=quote_text,
                )
            ],
            confidence=0.82,
            reality_layer=RealityLayer.PRIMARY,
        )
        provider_result = ProviderResultV1(
            provider_result_id="provider-result-smoke-1",
            provider_name="ustc-openai-compatible",
            provider_type=ProviderType.LLM,
            model_name="deepseek-v4-pro",
            output_schema="EventProposalV1",
            structured_output=proposal.model_dump(mode="json"),
            success=True,
            created_at=DETERMINISTIC_REAL_AUDIT_TIME,
        )
        agent_run = AgentRunV1(
            agent_run_id="agent-run-smoke-1",
            project_id=project_id,
            agent_name="event-extraction-agent",
            input_chunk_ids=chunk_ids,
            output_proposal_ids=[proposal.proposal_id],
            output_schema="EventProposalV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=AgentRunStatus.SUCCEEDED,
            started_at=DETERMINISTIC_REAL_AUDIT_TIME,
            completed_at=DETERMINISTIC_REAL_AUDIT_TIME,
            payload={
                "provider_result": provider_result.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
                "evidence_validation_passed": True,
            },
        )
        return type("FakeWorkflowResult", (), {"agent_run": agent_run, "proposal": proposal})()


def test_smoke_real_event_agent_summary_includes_sanitized_success_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("第一章 开端\n\n林夏推开门。", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_real_event_agent.RealEventWorkflow",
        FakeSuccessfulWorkflow,
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
    assert summary["provider_result_id"] == "provider-result-smoke-1"
    assert summary["provider_success"] is True
    assert summary["proposal_id"] == "proposal-smoke-1"
    assert summary["confidence"] == 0.82
    assert summary["actor_resolution_status"] == "KNOWN"
    assert summary["schema_validation_passed"] is True
    assert summary["evidence_chunk_id"] == summary["selected_chunk_ids"][0]
    assert summary["quote_matched"] is True
    assert summary["char_range_matched"] is True
    assert "secret-test-key" not in serialized
    assert "林夏推开门" not in serialized
