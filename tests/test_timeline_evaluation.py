"""Regression tests for the checked-in Timeline evaluation harness."""

import json
from collections import Counter
from pathlib import Path

import pytest

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.evaluation.timeline import (
    calculate_metrics,
    evaluate_case,
    load_timeline_gold_cases,
)
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.schemas.timeline import TimelineAnalysisMode
from scripts import eval_timeline

CASES = Path(__file__).parent / "gold" / "timeline" / "cases.jsonl"


def test_gold_set_has_30_balanced_traceable_cases() -> None:
    cases = load_timeline_gold_cases(CASES)

    assert len(cases) == 30
    assert len({case.case_id for case in cases}) == 30
    assert Counter(str(case.gold_relation) for case in cases) == {
        "BEFORE": 6,
        "AFTER": 6,
        "SIMULTANEOUS": 6,
        "OVERLAPS": 6,
        "UNKNOWN": 6,
    }
    assert sum(case.gold_conflict for case in cases) == 5
    assert sum(case.gold_duplicate for case in cases) == 5
    for case in cases:
        if case.gold_duplicate:
            assert case.event_a.summary != case.event_b.summary
            assert len(case.claim_proposals) == 2


def test_rules_baseline_is_safe_and_scores_deterministic_checks() -> None:
    cases = load_timeline_gold_cases(CASES)
    agent = TimelineAgent(llm_enabled=False)
    results = [
        evaluate_case(case, agent, TimelineAnalysisMode.RULES_ONLY) for case in cases
    ]
    metrics = calculate_metrics(results, TimelineAnalysisMode.RULES_ONLY.value)

    assert metrics["successful_cases"] == 30
    assert metrics["failed_cases"] == 0
    assert metrics["execution_success_rate"] == pytest.approx(1.0)
    relation = metrics["relation"]
    assert isinstance(relation, dict)
    assert relation["accuracy"] == pytest.approx(0.2)
    assert relation["successful_case_accuracy"] == pytest.approx(0.2)
    assert relation["attempted_case_accuracy"] == pytest.approx(0.2)
    assert relation["unknown_recall"] == pytest.approx(1.0)
    assert relation["unsupported_temporal_assertion_rate"] == pytest.approx(0.0)
    assert metrics["conflict"]["recall"] == pytest.approx(1.0)  # type: ignore[index]
    assert metrics["duplicate"]["recall"] == pytest.approx(1.0)  # type: ignore[index]


def test_execution_failure_is_not_counted_as_unknown() -> None:
    case = load_timeline_gold_cases(CASES)[0]
    result = evaluate_case(case, TimelineAgent(), TimelineAnalysisMode.LLM)
    metrics = calculate_metrics([result], TimelineAnalysisMode.LLM.value)

    assert result.status == "failed"
    assert result.predicted_relation is None
    assert metrics["successful_cases"] == 0
    assert metrics["failed_cases"] == 1
    assert metrics["execution_success_rate"] == pytest.approx(0.0)
    assert metrics["relation"]["attempted_case_accuracy"] == pytest.approx(0.0)  # type: ignore[index]
    assert metrics["failures_by_category"] == {"provider_or_schema": 1}


def test_provider_transport_failure_is_recorded_per_case() -> None:
    class FailingProvider:
        def structured_generate(self, request: object, response_model: object) -> object:
            raise ConnectionError("gateway unavailable")

    case = load_timeline_gold_cases(CASES)[0]
    result = evaluate_case(
        case,
        TimelineAgent(FailingProvider()),  # type: ignore[arg-type]
        TimelineAnalysisMode.LLM,
    )

    assert result.status == "failed"
    assert result.error_type == "ConnectionError"
    assert result.failure_category == "network"
    assert result.predicted_relation is None


def test_all_mode_writes_isolated_artifacts_and_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_agent(mode: str) -> TimelineAgent:
        if mode == "rules":
            return TimelineAgent(llm_enabled=False)
        return TimelineAgent(
            MockLLMProvider(
                {
                    "relation": "UNKNOWN",
                    "supporting_evidence_ids": [],
                    "confidence": 0.8,
                    "reasoning_summary": "No reliable temporal anchor.",
                }
            ),
            provider_model="mock-timeline",
        )

    monkeypatch.setattr(eval_timeline, "make_agent", fake_agent)
    run_dir = eval_timeline.run_evaluation(
        "all", cases_path=CASES, output_root=tmp_path, limit=2
    )

    comparison = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
    assert set(comparison) == {"rules", "llm"}
    for mode in ("rules", "llm"):
        assert (run_dir / mode / "results.json").is_file()
        assert (run_dir / mode / "failures.json").is_file()
        assert (run_dir / mode / "metrics.json").is_file()
        assert comparison[mode]["total_cases"] == 2


def test_resume_skips_successes_and_retries_failed_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        eval_timeline, "make_agent", lambda mode: TimelineAgent(llm_enabled=False)
    )
    run_dir = eval_timeline.run_evaluation(
        "rules", cases_path=CASES, output_root=tmp_path, limit=2, show_progress=False
    )
    results_path = run_dir / "rules" / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["status"] = "failed"
    results[0]["failure_category"] = "network"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    eval_timeline.run_evaluation(
        "rules",
        cases_path=CASES,
        limit=2,
        resume_dir=run_dir,
        show_progress=False,
    )

    resumed = json.loads(results_path.read_text(encoding="utf-8"))
    assert [result["status"] for result in resumed] == ["succeeded", "succeeded"]


def test_network_retry_is_bounded_and_visible_in_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FlakyAgent:
        calls = 0

        def run(self, input_context: object, *, source_chunks: object) -> object:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary gateway failure")
            return TimelineAgent(llm_enabled=False).run(  # type: ignore[arg-type]
                input_context, source_chunks=source_chunks  # type: ignore[arg-type]
            )

    agent = FlakyAgent()
    monkeypatch.setattr(eval_timeline, "make_agent", lambda mode: agent)
    run_dir = eval_timeline.run_evaluation(
        "llm",
        cases_path=CASES,
        output_root=tmp_path,
        limit=1,
        network_retries=1,
        show_progress=False,
    )

    metrics = json.loads((run_dir / "llm" / "metrics.json").read_text(encoding="utf-8"))
    assert agent.calls == 2
    assert metrics["successful_cases"] == 1
    assert metrics["failures_by_category"] == {}
