"""Explicit, local-only real Provider acceptance runner for the safe pipeline."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.config import Settings, get_settings
from comic_agent.main import create_app
from comic_agent.schemas.reliability import StructuredOutputPolicy

AcceptanceTier = Literal["short", "medium", "long"]
NARRATIVE_ACCEPTANCE_MODES = (
    "entity_extraction",
    "event_extraction",
    "claim_extraction",
    "knowledge_state_extraction",
    "state_change_extraction",
    "relationship_signal_extraction",
)


def _scene(index: int) -> str:
    return (
        f"第{index}节\n"
        f"傍晚，学生林岚在图书馆门口核对第{index}份志愿服务报名表。\n"
        "同学周宁带来活动海报，说明周六上午九点在报告厅集合。\n"
        "林岚把确认过的名单放入蓝色文件夹，并提醒周宁通知尚未回复的同学。\n"
    )


def acceptance_text(tier: AcceptanceTier) -> str:
    """Return fixed, non-sensitive text with increasing bounded narrative scope."""

    count = {"short": 2, "medium": 10, "long": 30}[tier]
    return "\n".join(_scene(index) for index in range(1, count + 1))


def pipeline_form(*, tier: AcceptanceTier) -> dict[str, str]:
    """Build the one-click API form that explicitly requests all six modes."""

    return {
        "project_name": f"Local real Provider acceptance ({tier})",
        "real_llm_requested": "true",
        "narrative_modes": json.dumps(list(NARRATIVE_ACCEPTANCE_MODES)),
    }


def validate_live_settings(settings: Settings) -> None:
    """Fail closed before creating a database or making any Provider request."""

    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if settings.comic_agent_env != "development":
        raise ValueError("COMIC_AGENT_ENV must be development for local acceptance")
    if not settings.enable_real_llm:
        raise ValueError("ENABLE_REAL_LLM must be true for local acceptance")
    if settings.fake_pipeline_demo:
        raise ValueError("COMIC_AGENT_FAKE_PIPELINE_DEMO must be false for local acceptance")
    if not key:
        raise ValueError("a local LLM_API_KEY or OPENAI_API_KEY is required")
    if settings.llm_structured_output_policy == StructuredOutputPolicy.JSON_OBJECT_ONLY:
        raise ValueError(
            "LLM_STRUCTURED_OUTPUT_POLICY must be AUTO or REQUIRE_STRICT for this acceptance"
        )


def _safe_summary(payload: dict[str, object], *, tier: AcceptanceTier) -> dict[str, object]:
    """Retain only progress and safe diagnostics; never write source/provider output."""

    keys = (
        "gate1",
        "narrative",
        "narrative_failure_summary",
        "batch_summary",
        "window_summary",
        "structured_execution",
        "provider_health",
        "gate2",
        "narrative_recovery",
        "timeline",
        "timeline_recovery",
        "gate3",
        "approved_timeline_bundle_id",
        "safe_issue_codes",
        "gate3_issue_count",
    )
    return {
        "schema_version": "1.0",
        "tier": tier,
        "completed_at": datetime.now(UTC).isoformat(),
        **{key: payload.get(key) for key in keys},
    }


def run_acceptance(
    *, tier: AcceptanceTier, output_dir: Path, settings: Settings
) -> dict[str, object]:
    """Run one explicit tier in an isolated local database and return a safe summary."""

    validate_live_settings(settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_token = uuid4().hex[:12]
    database_path = output_dir / f"real-provider-{tier}-{run_token}.db"
    project_id = f"local-real-acceptance-{tier}-{run_token}"
    app = create_app(database_url=f"sqlite+pysqlite:///{database_path}")
    with TestClient(app) as client:
        started = client.post(
            f"/projects/{project_id}/pipeline-runs/import-and-analyze",
            data=pipeline_form(tier=tier),
            files={
                "file": (
                    f"acceptance-{tier}.txt",
                    acceptance_text(tier).encode("utf-8"),
                    "text/plain",
                )
            },
        )
        if started.status_code != 200:
            detail = None
            if started.headers.get("content-type", "").startswith("application/json"):
                detail = started.json().get("detail")
            return {
                "schema_version": "1.0",
                "tier": tier,
                "start_status": "REJECTED",
                "http_status": started.status_code,
                "detail": detail if isinstance(detail, (dict, list, str)) else "START_REJECTED",
            }
        run_id = started.json().get("analysis_run_id")
        if not isinstance(run_id, str):
            raise RuntimeError("pipeline did not return an analysis_run_id")
        status = client.get(f"/pipeline-runs/{run_id}")
        if status.status_code != 200:
            raise RuntimeError("pipeline status endpoint did not return 200")
        return _safe_summary(status.json(), tier=tier)


def _exit_code(summary: dict[str, object]) -> int:
    if summary.get("start_status") == "REJECTED":
        return 3
    required = {
        "narrative": "SUCCEEDED",
        "gate2": "APPROVED",
        "timeline": "APPROVED",
        "gate3": "APPROVED",
    }
    return 0 if all(summary.get(key) == value for key, value in required.items()) else 4


def main() -> None:
    """Parse the explicit opt-in CLI without accepting secrets as arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=("short", "medium", "long"), required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("runs/local-real-provider-acceptance")
    )
    parser.add_argument("--run-real", action="store_true")
    args = parser.parse_args()
    if not args.run_real:
        parser.error("--run-real is required; this command otherwise makes no Provider request")

    get_settings.cache_clear()
    settings = get_settings()
    try:
        summary = run_acceptance(tier=args.tier, output_dir=args.output_dir, settings=settings)
    except ValueError as exc:
        summary = {
            "schema_version": "1.0",
            "tier": args.tier,
            "start_status": "BLOCKED",
            "detail": str(exc),
        }
    finally:
        get_settings.cache_clear()
    path = args.output_dir / f"{args.tier}-summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(_exit_code(summary))


if __name__ == "__main__":
    main()
