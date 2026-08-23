"""Runner-only readiness checks that never invoke a provider."""

import importlib.util
import sqlite3
import time
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest


def _runner_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "run_production_e2e.py"
    spec = importlib.util.spec_from_file_location("run_production_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _API:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.calls = 0

    def request(self, method: str, path: str) -> dict[str, object]:
        assert method == "GET"
        assert path.endswith("/run-1")
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class _Log:
    def write(self, message: str = "") -> None:
        pass


def _run(status: str, *, ready: bool) -> dict[str, object]:
    return {
        "status": status,
        "windows_succeeded": 2,
        "windows_failed": 0,
        "review_gate2_ready": ready,
    }


def test_poll_narrative_waits_for_automatic_gate2_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    api = _API([_run("SUCCEEDED", ready=False), _run("SUCCEEDED", ready=True)])

    result = runner.poll_narrative(api, "run-1", time.monotonic() + 5, _Log())

    assert result["review_gate2_ready"] is True
    assert api.calls == 2


def test_poll_narrative_returns_narrative_failure_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    api = _API([_run("FAILED", ready=False)])

    result = runner.poll_narrative(api, "run-1", time.monotonic() + 5, _Log())

    assert result["status"] == "FAILED"
    assert api.calls == 1


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _ResumeAPI:
    def __init__(
        self,
        decision: str,
        *,
        human_decision: str | None = None,
        bundle_available: bool = False,
    ) -> None:
        self.decision = decision
        self.human_decision = human_decision
        self.bundle_available = bundle_available
        self.post_calls = 0
        self.client = self

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            self.post_calls += 1
            raise AssertionError(f"resume unexpectedly posted to {path}")
        if path == "/settings/llm/status":
            return {"provider_name": "fixture", "model": "fixture-model"}
        if path == "/narrative-analysis-runs/run-1":
            return {
                "analysis_run_id": "run-1",
                "project_id": "project-1",
                "document_id": "document-1",
                "status": "SUCCEEDED",
                "windows_succeeded": 1,
                "windows_failed": 0,
                "windows_total": 1,
                "review_gate2_ready": True,
            }
        if path == "/narrative-analysis-runs/run-1/review-gate2":
            return {
                "route": {
                    "decision": "APPROVED",
                    "approved_count": 1,
                    "rejected_count": 0,
                    "approved_proposal_bundle": {"bundle_id": "gate2-bundle-1"},
                }
            }
        if path.endswith("/review"):
            human = (
                {"final_decision": self.human_decision}
                if self.human_decision is not None
                else None
            )
            return {
                "result": {
                    "decision": "NEEDS_HUMAN_REVIEW" if human else self.decision,
                    "effective_decision": self.decision if human else None,
                    "human_review": human,
                    "issues": [{"issue_id": "issue-1"}],
                },
                "route": {"route": "NEEDS_HUMAN_REVIEW" if human else self.decision},
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    def get(self, path: str) -> _Response:
        if path.endswith("/approved-bundle"):
            if not self.bundle_available:
                return _Response(409, {})
            return _Response(
                200,
                {
                    "bundle_id": "approved-timeline-1",
                    "timeline_run_id": "timeline-run-1",
                },
            )
        return _Response(
            200,
            {
                "gate3_ready": True,
                "timeline_run_id": "timeline-run-1",
            },
        )

    def close(self) -> None:
        pass


def _resume_result(runner: ModuleType) -> dict[str, Any]:
    return {
        "project_id": None,
        "document_id": None,
        "narrative_run_id": None,
        "timeline_proposal_id": None,
        "timeline_run_id": None,
        "gate3_run_id": None,
        "gate2_approved_bundle_id": None,
        "approved_timeline_bundle_id": None,
        "stage_status": {stage: "NOT REACHED" for stage in runner.STAGES},
        "counts": {},
        "failure_stage": None,
        "failure_category": None,
        "artifact_paths": {},
    }


def _exercise_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision: str,
    human_decision: str | None = None,
    bundle_available: bool = False,
) -> tuple[str, dict[str, Any], _ResumeAPI, int]:
    runner = _runner_module()
    source_database = tmp_path / "source.sqlite"
    with sqlite3.connect(source_database) as connection:
        connection.execute("CREATE TABLE source_chunks (project_id TEXT, chunk_id TEXT, text TEXT)")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    api = _ResumeAPI(
        decision,
        human_decision=human_decision,
        bundle_available=bundle_available,
    )
    preflight_calls = 0

    def preflight(*args: Any, **kwargs: Any) -> None:
        nonlocal preflight_calls
        preflight_calls += 1

    monkeypatch.setattr(runner, "find_resume_database", lambda _: source_database)
    monkeypatch.setattr(runner, "run_preflight", preflight)
    monkeypatch.setattr(runner, "free_port", lambda *_: 8011)
    monkeypatch.setattr(runner, "start_api", lambda *_: object())
    monkeypatch.setattr(runner, "wait_for_api", lambda *_: None)
    monkeypatch.setattr(runner, "stop_process", lambda *_: None)
    monkeypatch.setattr(runner, "API", lambda *_: api)
    monkeypatch.setattr(
        runner,
        "get_settings",
        lambda: SimpleNamespace(
            timeline_model="timeline-model",
            storybible_model="story-model",
            llm_model="narrative-model",
        ),
    )
    monkeypatch.setattr(
        runner,
        "db_counts",
        lambda *_: {
            "documents": 1,
            "chapters": 1,
            "chunks": 1,
            "narrative_analysis_runs": 1,
            "event_proposals": 0,
            "timeline_proposals": 0,
            "gate3_runs": 1,
            "narrative_windows": 1,
        },
    )
    monkeypatch.setattr(
        runner,
        "gate3_payload",
        lambda *_: {
            "timeline_run_id": "timeline-run-1",
            "timeline_input": {"mode": "LLM"},
            "timeline_proposal": {
                "proposal_id": "timeline-proposal-1",
                "temporal_relations": [],
                "conflicts": [],
                "duplicate_candidates": [],
            },
        },
    )
    result = _resume_result(runner)
    args = Namespace(
        source=tmp_path / "does-not-need-to-exist.txt",
        port=8011,
        timeout=5,
        resume_run="run-1",
        verbose=False,
    )
    outcome = runner.execute(args, output_dir, _Log(), result)
    return outcome, result, api, preflight_calls


def test_gate3_needs_human_review_is_a_business_block_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome, result, api, preflight_calls = _exercise_resume(
        tmp_path,
        monkeypatch,
        decision="NEEDS_HUMAN_REVIEW",
    )

    assert outcome == "BLOCKED_ON_HUMAN_REVIEW"
    assert result["stage_status"]["Gate 3"] == "PASS"
    assert result["stage_status"]["Approved Timeline Bundle"] == outcome
    assert result["gate3_run_id"] == result["timeline_run_id"] == "timeline-run-1"
    assert result["gate3_issue_ids"] == ["issue-1"]
    assert api.post_calls == preflight_calls == 0


def test_resume_after_human_approval_completes_without_llm_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome, result, api, preflight_calls = _exercise_resume(
        tmp_path,
        monkeypatch,
        decision="APPROVED",
        human_decision="APPROVED",
        bundle_available=True,
    )

    assert outcome == "COMPLETED"
    assert result["human_review_decision"] == "APPROVED"
    assert result["approved_timeline_bundle_id"] == "approved-timeline-1"
    assert result["narrative_run_id"] == "run-1"
    assert result["gate2_approved_bundle_id"] == "gate2-bundle-1"
    assert result["timeline_run_id"] == result["gate3_run_id"] == "timeline-run-1"
    assert api.post_calls == preflight_calls == 0


def test_resume_after_human_rejection_is_not_a_technical_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome, result, api, preflight_calls = _exercise_resume(
        tmp_path,
        monkeypatch,
        decision="REJECTED",
        human_decision="REJECTED",
    )

    assert outcome == "REJECTED_BY_HUMAN"
    assert result["stage_status"]["Gate 3"] == "PASS"
    assert result["stage_status"]["Approved Timeline Bundle"] == "NOT_CREATED"
    assert api.post_calls == preflight_calls == 0


def test_automatic_gate3_approval_still_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, result, _, _ = _exercise_resume(
        tmp_path,
        monkeypatch,
        decision="APPROVED",
        bundle_available=True,
    )

    assert outcome == "COMPLETED"
    assert result["human_review_decision"] is None


def test_approved_without_bundle_requires_existing_finalization_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match="bundle finalization") as exc_info:
        _exercise_resume(
            tmp_path,
            monkeypatch,
            decision="APPROVED",
            human_decision="APPROVED",
            bundle_available=False,
        )
    assert cast(Any, exc_info.value).category == "FINALIZATION_REQUIRED"


def test_invalid_gate3_state_remains_a_genuine_failure() -> None:
    runner = _runner_module()
    with pytest.raises(runner.E2EFailure) as exc_info:
        runner.gate3_business_decision(
            {"result": {"decision": "CORRUPT"}, "route": {"route": "CORRUPT"}}
        )
    assert exc_info.value.category == "DATABASE"
