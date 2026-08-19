"""Evaluate TimelineAgent against the checked-in timeline Gold Set."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_agent.agents.timeline_agent import TimelineAgent  # noqa: E402
from comic_agent.config import get_settings  # noqa: E402
from comic_agent.evaluation.timeline import (  # noqa: E402
    TimelineEvaluationResult,
    calculate_metrics,
    evaluate_case,
    load_timeline_gold_cases,
    result_to_json,
    write_json,
)
from comic_agent.providers.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from comic_agent.schemas.timeline import TimelineAnalysisMode  # noqa: E402

CASES = ROOT / "tests" / "gold" / "timeline" / "cases.jsonl"


def make_agent(mode: str) -> TimelineAgent:
    if mode == "rules":
        return TimelineAgent(llm_enabled=False)
    settings = get_settings()
    if not settings.timeline_llm_enabled or settings.llm_api_key is None:
        raise RuntimeError("LLM evaluation requested but LLM configuration is unavailable.")
    return TimelineAgent(
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.timeline_model or settings.llm_model,
            timeout_seconds=settings.timeline_llm_timeout_seconds,
            max_retries=settings.timeline_llm_max_retries,
        ),
        provider_model=settings.timeline_model or settings.llm_model,
    )


def run_evaluation(
    mode: str,
    *,
    cases_path: Path = CASES,
    output_root: Path | None = None,
    limit: int | None = None,
    resume_dir: Path | None = None,
    network_retries: int = 0,
    show_progress: bool = True,
) -> Path:
    """Run one or both modes and return the isolated artifact directory."""

    cases = load_timeline_gold_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]
    modes = ["rules", "llm"] if mode == "all" else [mode]
    if network_retries < 0:
        raise ValueError("network_retries must be non-negative")
    root = output_root or ROOT / "artifacts" / "timeline_eval"
    run_dir = resume_dir or root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    if resume_dir is not None and not resume_dir.is_dir():
        raise ValueError(f"resume directory does not exist: {resume_dir}")
    reports: dict[str, object] = {}
    for selected_mode in modes:
        timeline_mode = (
            TimelineAnalysisMode.RULES_ONLY
            if selected_mode == "rules"
            else TimelineAnalysisMode.LLM
        )
        directory = run_dir / selected_mode
        existing = _load_results(directory / "results.json") if resume_dir else []
        results_by_id = {
            result.case_id: result for result in existing if result.status == "succeeded"
        }
        pending = [case for case in cases if case.case_id not in results_by_id]
        agent = make_agent(selected_mode) if pending else None
        started = perf_counter()
        completed = 0
        for case in pending:
            assert agent is not None
            attempts = 0
            while True:
                result = evaluate_case(case, agent, timeline_mode)
                if result.failure_category != "network" or attempts >= network_retries:
                    break
                attempts += 1
                if show_progress:
                    print(
                        f"[{selected_mode}] retry {case.case_id} after network failure "
                        f"({attempts}/{network_retries})",
                        flush=True,
                    )
            results_by_id[case.case_id] = result
            completed += 1
            ordered = [
                results_by_id[item.case_id]
                for item in cases
                if item.case_id in results_by_id
            ]
            _write_mode_artifacts(directory, ordered, timeline_mode)
            if show_progress:
                elapsed = perf_counter() - started
                remaining = len(pending) - completed
                eta = elapsed / completed * remaining
                print(
                    f"[{selected_mode}] {completed}/{len(pending)} {case.case_id} "
                    f"{result.status}; ETA {_format_duration(eta)}",
                    flush=True,
                )
        results = [results_by_id[case.case_id] for case in cases if case.case_id in results_by_id]
        _write_mode_artifacts(directory, results, timeline_mode)
        metrics = calculate_metrics(results, timeline_mode.value)
        reports[selected_mode] = metrics
    if mode == "all":
        write_json(run_dir / "comparison.json", reports)
    return run_dir


def _load_results(path: Path) -> list[TimelineEvaluationResult]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [TimelineEvaluationResult(**item) for item in payload]


def _write_mode_artifacts(
    directory: Path,
    results: list[TimelineEvaluationResult],
    mode: TimelineAnalysisMode,
) -> None:
    write_json(directory / "results.json", [result_to_json(result) for result in results])
    write_json(
        directory / "failures.json",
        [result_to_json(result) for result in results if result.status == "failed"],
    )
    write_json(directory / "metrics.json", calculate_metrics(results, mode.value))


def _format_duration(seconds: float) -> str:
    rounded = max(0, round(seconds))
    minutes, remaining_seconds = divmod(rounded, 60)
    return f"{minutes}m{remaining_seconds:02d}s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rules", "llm", "all"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--network-retries", type=int, default=0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    run_dir = run_evaluation(
        args.mode,
        limit=args.limit,
        resume_dir=args.resume,
        network_retries=args.network_retries,
        show_progress=not args.quiet,
    )
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
