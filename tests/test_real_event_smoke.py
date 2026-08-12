import json
from pathlib import Path
from typing import Any

from comic_agent.config import Settings
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    ActorResolutionStatus,
    EventProposalBatchV1,
    EventProposalV1,
)
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
    assert "key_status" not in summary
    assert "secret-test-key" not in serialized
    assert "林夏推开门" not in serialized
    assert (tmp_path / "out" / "real_event_agent_smoke_summary.json").exists()


def test_smoke_real_event_agent_dry_run_supports_three_chunk_summary(
    tmp_path: Path,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text(
        "First event paragraph.\n\nSecond event paragraph.\n\nThird event paragraph.",
        encoding="utf-8",
    )

    summary = run_smoke(
        project_id="project-1",
        txt_path=txt_path,
        output_dir=tmp_path / "out",
        chunk_limit=3,
        enable_real_llm=False,
        settings=Settings(_env_file=None, llm_api_key="secret-test-key"),
    )

    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["dry_run"] is True
    assert summary["real_llm_requested"] is False
    assert summary["real_llm_called"] is False
    assert summary["selected_chunks_count"] == 3
    assert summary["context_chunk_ids"] == summary["selected_chunk_ids"]
    assert summary["agent_run_saved"] is False
    assert summary["evidence_validation_passed"] is None
    assert "First event paragraph" not in serialized
    assert "Second event paragraph" not in serialized
    assert "Third event paragraph" not in serialized
    assert "secret-test-key" not in serialized
    assert "key_status" not in summary


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
        batch = EventProposalBatchV1(batch_id="event-batch-smoke-1", events=[proposal])
        provider_result = ProviderResultV1(
            provider_result_id="provider-result-smoke-1",
            provider_name="ustc-openai-compatible",
            provider_type=ProviderType.LLM,
            model_name="deepseek-v4-pro",
            output_schema="EventProposalBatchV1",
            structured_output=batch.model_dump(mode="json"),
            success=True,
            created_at=DETERMINISTIC_REAL_AUDIT_TIME,
        )
        agent_run = AgentRunV1(
            agent_run_id="agent-run-smoke-1",
            project_id=project_id,
            agent_name="event-extraction-agent",
            input_chunk_ids=chunk_ids,
            output_proposal_ids=[proposal.proposal_id],
            output_schema="EventProposalBatchV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=AgentRunStatus.SUCCEEDED,
            started_at=DETERMINISTIC_REAL_AUDIT_TIME,
            completed_at=DETERMINISTIC_REAL_AUDIT_TIME,
            payload={
                "provider_result": provider_result.model_dump(mode="json"),
                "proposal": batch.model_dump(mode="json"),
                "evidence_validation_passed": True,
            },
        )
        return type("FakeWorkflowResult", (), {"agent_run": agent_run, "proposal": batch})()


class FakeFailedDiagnosticWorkflow:
    def __init__(self, **kwargs: Any) -> None:
        self.source_repository = kwargs["source_repository"]

    def run(self, project_id: str, chunk_ids: list[str]):
        diagnostics = {
            "finish_reason": "stop",
            "response_has_choices": True,
            "choices_count": 1,
            "message_keys": ["content", "reasoning_content"],
            "content_type": "NoneType",
            "has_reasoning_content": True,
            "has_tool_calls": False,
            "usage_prompt_tokens": 12,
            "usage_completion_tokens": 0,
            "usage_total_tokens": 12,
        }
        provider_result = ProviderResultV1(
            provider_result_id="provider-result-smoke-failed",
            provider_name="ustc-openai-compatible",
            provider_type=ProviderType.LLM,
            model_name="deepseek-v4-pro",
            output_schema="EventProposalBatchV1",
            success=False,
            error_message="LLM provider response content is missing",
            created_at=DETERMINISTIC_REAL_AUDIT_TIME,
        )
        agent_run = AgentRunV1(
            agent_run_id="agent-run-smoke-failed",
            project_id=project_id,
            agent_name="event-extraction-agent",
            input_chunk_ids=chunk_ids,
            output_schema="EventProposalBatchV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=AgentRunStatus.FAILED,
            started_at=DETERMINISTIC_REAL_AUDIT_TIME,
            completed_at=DETERMINISTIC_REAL_AUDIT_TIME,
            error_message="LLM provider response content is missing",
            payload={
                "provider_result": provider_result.model_dump(mode="json"),
                "provider_error_diagnostics": diagnostics,
                "proposal": None,
                "evidence_validation_passed": False,
            },
        )
        return type("FakeWorkflowResult", (), {"agent_run": agent_run, "proposal": None})()


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
    assert summary["batch_id"] == "event-batch-smoke-1"
    assert summary["events_count"] == 1
    assert summary["event_proposal_ids"] == ["proposal-smoke-1"]
    assert summary["primary_event_type"] == "discovery"
    assert summary["schema_validation_passed"] is True
    assert summary["quote_matched"] is True
    assert summary["char_range_matched"] is True
    assert "secret-test-key" not in serialized
    assert "林夏推开门" not in serialized


def test_smoke_real_event_agent_summary_includes_sanitized_failure_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    txt_path = tmp_path / "source.txt"
    txt_path.write_text("第一章 开端\n\n林夏推开门。", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.smoke_real_event_agent.RealEventWorkflow",
        FakeFailedDiagnosticWorkflow,
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
    assert summary["provider_success"] is False
    assert summary["schema_validation_passed"] is False
    assert summary["provider_error_diagnostics"] == {
        "finish_reason": "stop",
        "response_has_choices": True,
        "choices_count": 1,
        "message_keys": ["content", "reasoning_content"],
        "content_type": "NoneType",
        "has_reasoning_content": True,
        "has_tool_calls": False,
        "usage_prompt_tokens": 12,
        "usage_completion_tokens": 0,
        "usage_total_tokens": 12,
    }
    assert summary["usage_prompt_tokens"] == 12
    assert summary["usage_completion_tokens"] == 0
    assert summary["usage_total_tokens"] == 12
    assert "secret-test-key" not in serialized
    assert "林夏推开门" not in serialized
