"""Offline safety tests for the current real pipeline acceptance runner."""

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from comic_agent.config import Settings
from scripts.run_current_real_pipeline_acceptance import (
    AcceptanceFailure,
    initial_result,
    mark_after_failure,
    preflight,
    record_narrative_diagnostics,
    resolved_timeline_bundle_id,
    run_stage,
    sanitize,
    summarize_provider_usage,
    timeline_can_reach_gate3,
    validate_provider,
)


def test_preflight_initializes_database_without_provider_call(tmp_path: Path) -> None:
    fixture = tmp_path / "story.txt"
    fixture.write_text("林岚在北门换好门锁。", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = initial_result(run_dir)
    settings = Settings(_env_file=None)

    preflight(Namespace(input=fixture), result, settings)

    assert result["result"] == "PREFLIGHT_PASS"
    assert (run_dir / "e2e.sqlite").exists()
    assert result["provider_calls"] == {}
    # Preflight must not falsely report unexecuted stages as PASS.
    assert result["stage_status"]["document_import"] == "PASS"
    assert result["stage_status"]["narrative"] == "NOT_STARTED"
    assert result["stage_status"]["comic_planning"] == "NOT_STARTED"
    assert result["stage_status"]["panel_validation"] == "NOT_STARTED"


def test_first_failure_wins_and_downstream_is_skipped(tmp_path: Path) -> None:
    result = initial_result(tmp_path)
    calls: list[str] = []

    with pytest.raises(RuntimeError):
        run_stage(result, "narrative", lambda: (_ for _ in ()).throw(RuntimeError("first")))
    mark_after_failure(result, "narrative")
    if result["stage_status"]["timeline"] != "SKIPPED_AFTER_FAILURE":
        calls.append("timeline")

    assert calls == []
    assert result["stage_status"]["narrative"] == "FAIL"
    assert result["stage_status"]["panel_validation"] == "SKIPPED_AFTER_FAILURE"


def test_timeline_needing_human_review_continues_to_gate3_resolution() -> None:
    assert timeline_can_reach_gate3("NEEDS_HUMAN_REVIEW") is True
    assert timeline_can_reach_gate3("APPROVED") is True
    assert timeline_can_reach_gate3("FAILED") is False


def test_review_response_supplies_bundle_when_pipeline_status_is_stale() -> None:
    assert resolved_timeline_bundle_id(
        {"approved_timeline_bundle_id": None},
        {"approved_timeline_bundle_id": "timeline-bundle-1"},
    ) == "timeline-bundle-1"


def test_provider_usage_sums_only_allowlisted_metadata() -> None:
    executions = [
        SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
        SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        SimpleNamespace(prompt_tokens=None, completion_tokens=None, total_tokens=None),
    ]

    assert summarize_provider_usage(executions) == {
        "calls": 3,
        "reported_calls": 2,
        "prompt_tokens": 30,
        "completion_tokens": 9,
        "total_tokens": 39,
    }


def test_secrets_are_redacted() -> None:
    settings = Settings(_env_file=None, llm_api_key="super-secret")
    value = sanitize("Authorization: Bearer super-secret API_KEY=super-secret", settings)
    assert "super-secret" not in value


@pytest.mark.parametrize("provider", ["mock", "fake-provider", "test-llm", "local-demo"])
def test_mock_or_fallback_provider_is_rejected(provider: str) -> None:
    settings = Settings(
        _env_file=None,
        enable_real_llm=True,
        timeline_llm_enabled=True,
        llm_api_key="x",
        llm_provider_name=provider,
    )
    with pytest.raises(AcceptanceFailure) as caught:
        validate_provider(settings)
    assert caught.value.category == "MOCK_OR_FALLBACK_PROVIDER"


def test_result_shape_can_be_written_on_failure(tmp_path: Path) -> None:
    result = initial_result(tmp_path)
    result.update(result="FAIL", failure_stage="narrative", failure_category="PROVIDER")
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["failure_stage"] == "narrative"
    assert set(restored["stage_status"]) >= {"storybible_curator", "panel_validation"}


def test_narrative_terminal_failure_diagnostics_are_propagated(tmp_path: Path) -> None:
    result = initial_result(tmp_path)
    window = SimpleNamespace(
        mode="event_extraction",
        status="FAILED",
        provider_request_count=2,
        attempt_count=2,
        failure_category="PROVIDER_LENGTH_BEFORE_FINAL_CONTENT",
        provider_finish_reason="length",
        provider_completion_tokens=2000,
    )
    first_execution = SimpleNamespace(
        schema_diagnostics={"schema_error_field_paths": ["events.0", "events.1"]}
    )
    attempts = [
        SimpleNamespace(
            agent_run_id="agent-run-1",
            payload={"input_context": {"mode": "event_extraction"}},
            provider_result=SimpleNamespace(execution_metadata=first_execution),
        ),
        SimpleNamespace(
            agent_run_id="agent-run-2",
            payload={"input_context": {"mode": "event_extraction"}},
            provider_result=SimpleNamespace(
                execution_metadata=SimpleNamespace(schema_diagnostics=None)
            ),
        ),
    ]

    category = record_narrative_diagnostics(result, [window], attempts)

    assert category == "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT"
    assert result["provider_calls"] == {"narrative": 2}
    assert result["counts"] == {
        "narrative_requested_modes": 1,
        "narrative_successful_modes": 0,
        "narrative_failed_modes": 1,
        "narrative_attempts": 2,
    }
    assert result["narrative_modes"]["event_extraction"] == {
        "status": "FAILED",
        "agent_run_ids": ["agent-run-1", "agent-run-2"],
        "provider_request_count": 2,
        "attempt_count": 2,
        "failure_category": "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT",
        "finish_reason": "length",
        "completion_tokens": 2000,
        "schema_error_field_paths": ["events.0", "events.1"],
    }


def test_narrative_failure_does_not_mark_downstream_pass(tmp_path: Path) -> None:
    result = initial_result(tmp_path)
    result["stage_status"]["document_import"] = "PASS"
    result["stage_status"]["gate1"] = "PASS"
    result["stage_status"]["chunking"] = "PASS"
    result["stage_status"]["narrative"] = "FAIL"

    mark_after_failure(result, "narrative")

    assert result["stage_status"]["gate2"] == "SKIPPED_AFTER_FAILURE"
    assert result["stage_status"]["timeline"] == "SKIPPED_AFTER_FAILURE"
    assert result["stage_status"]["gate3"] == "SKIPPED_AFTER_FAILURE"


def test_narrative_diagnostics_never_include_provider_raw_content(tmp_path: Path) -> None:
    result = initial_result(tmp_path)
    window = SimpleNamespace(
        mode="event_extraction",
        status="FAILED",
        provider_request_count=1,
        attempt_count=1,
        failure_category="SCHEMA_VALIDATION_FAILED",
        provider_finish_reason="stop",
        provider_completion_tokens=20,
    )
    attempt = SimpleNamespace(
        agent_run_id="agent-run-safe",
        payload={
            "input_context": {"mode": "event_extraction"},
            "raw_output": "Bearer secret-value",
        },
        provider_result=SimpleNamespace(
            execution_metadata=SimpleNamespace(schema_diagnostics=None)
        ),
    )

    record_narrative_diagnostics(result, [window], [attempt])

    serialized = json.dumps(result)
    assert "secret-value" not in serialized
    assert "raw_output" not in serialized
