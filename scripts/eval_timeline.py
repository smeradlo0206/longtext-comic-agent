"""Evaluate TimelineAgent against the checked-in timeline Gold Set."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.config import get_settings
from comic_agent.evaluation.timeline import (
    calculate_metrics,
    evaluate_case,
    load_timeline_gold_cases,
    result_to_json,
    write_json,
)
from comic_agent.providers.openai_compatible import OpenAICompatibleProvider
from comic_agent.schemas.timeline import TimelineAnalysisMode

ROOT = Path(__file__).resolve().parents[1]
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rules", "llm", "all"), required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    cases = load_timeline_gold_cases(CASES)
    if args.limit is not None:
        cases = cases[: args.limit]
    modes = ["rules", "llm"] if args.mode == "all" else [args.mode]
    run_dir = ROOT / "artifacts" / "timeline_eval" / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    reports: dict[str, object] = {}
    for mode in modes:
        timeline_mode = TimelineAnalysisMode.RULES_ONLY if mode == "rules" else TimelineAnalysisMode.LLM
        results = [evaluate_case(case, make_agent(mode), timeline_mode) for case in cases]
        directory = run_dir / mode
        write_json(directory / "results.json", [result_to_json(result) for result in results])
        write_json(directory / "failures.json", [result_to_json(result) for result in results if result.status == "failed"])
        metrics = calculate_metrics(results, timeline_mode.value)
        write_json(directory / "metrics.json", metrics)
        reports[mode] = metrics
    if args.mode == "all":
        write_json(run_dir / "comparison.json", reports)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
