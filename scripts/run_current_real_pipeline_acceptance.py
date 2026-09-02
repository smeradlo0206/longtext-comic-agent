"""One-shot acceptance for the current real Narrative-to-Panel production pipeline.

``--preflight-only`` is deliberately network-free.  A normal invocation is the
explicit opt-in boundary for real Provider calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_agent.config import Settings, get_settings  # noqa: E402
from comic_agent.domain.identity import storybible_proposal_hash  # noqa: E402
from comic_agent.main import create_app  # noqa: E402
from comic_agent.repositories.agent_run_repository import AgentRunRepository  # noqa: E402
from comic_agent.repositories.narrative_analysis_repository import (  # noqa: E402
    NarrativeAnalysisRepository,
)
from comic_agent.repositories.source_repository import SourceRepository  # noqa: E402
from comic_agent.repositories.storybible_production_run_repository import (  # noqa: E402
    StoryBibleProductionRunRepository,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository  # noqa: E402
from comic_agent.repositories.storybible_review_repository import (  # noqa: E402
    StoryBibleReviewRepository,
)
from comic_agent.repositories.timeline_gate3_repository import (  # noqa: E402
    TimelineGate3Repository,
)
from comic_agent.schemas.storybible import (  # noqa: E402
    StoryBibleProductionRunStatus,
    StoryBibleReviewContextV1,
)
from comic_agent.services.comic_planning_service import ComicPlanningService  # noqa: E402
from comic_agent.services.commit_service import CommitService  # noqa: E402
from comic_agent.services.id_service import stable_id  # noqa: E402
from comic_agent.services.panel_planning_service import PanelPlanningService  # noqa: E402
from comic_agent.services.storybible_freeze_service import StoryBibleFreezeService  # noqa: E402
from comic_agent.services.storybible_production_context import (  # noqa: E402
    StoryBibleProductionContextAdapter,
    StoryBibleProductionInputBuilder,
)
from comic_agent.services.storybible_production_coordinator import (  # noqa: E402
    StoryBibleProductionCoordinator,
)
from comic_agent.services.storybible_production_output_normalizer import (  # noqa: E402
    StoryBibleProductionOutputNormalizer,
)
from comic_agent.services.storybible_review_service import StoryBibleReviewService  # noqa: E402

DEFAULT_INPUT = ROOT / "tests" / "fixtures" / "acceptance" / "current_real_pipeline_short.txt"
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "current-real-pipeline-acceptance"
NARRATIVE_MODES = (
    "entity_extraction",
    "event_extraction",
    "claim_extraction",
    "knowledge_state_extraction",
    "state_change_extraction",
    "relationship_signal_extraction",
)
STAGES = (
    "document_import",
    "gate1",
    "chunking",
    "narrative",
    "gate2",
    "timeline_adapter",
    "timeline",
    "gate3",
    "human_review",
    "approved_timeline",
    "storybible_context",
    "storybible_curator",
    "storybible_normalization",
    "storybible_review",
    "storybible_freeze",
    "approved_storybible",
    "comic_planning",
    "scene_validation",
    "panel_planning",
    "panel_validation",
)
SECRET_RE = re.compile(r"(?i)(authorization|bearer|api[_-]?key|token)(\s*[:=]\s*)(\S+)")


class AcceptanceFailure(RuntimeError):
    def __init__(self, stage: str, category: str, message: str) -> None:
        super().__init__(message)
        self.stage, self.category = stage, category


def sanitize(value: object, settings: Settings | None = None) -> str:
    text = " ".join(str(value).splitlines())
    if settings and settings.llm_api_key:
        key = settings.llm_api_key.get_secret_value()
        if key:
            text = text.replace(key, "[REDACTED]")
    return SECRET_RE.sub(r"\1\2[REDACTED]", text)[:2000]


def initial_result(run_dir: Path) -> dict[str, Any]:
    return {
        "result": None,
        "failure_stage": None,
        "failure_category": None,
        "exception_type": None,
        "sanitized_error": None,
        "project_id": None,
        "document_id": None,
        "narrative_run_id": None,
        "approved_timeline_bundle_id": None,
        "storybible_production_run_id": None,
        "curator_agent_run_id": None,
        "storybible_review_run_id": None,
        "approved_storybible_bundle_id": None,
        "snapshot_hash": None,
        "scene_count": 0,
        "panel_count": 0,
        "mock_or_fallback_used": None,
        "previous_curator_length_failure": None,
        "narrative_modes": {},
        "stage_status": {stage: "NOT_STARTED" for stage in STAGES},
        "provider_calls": {},
        "counts": {},
        "artifact_paths": {
            "directory": str(run_dir),
            "database": str(run_dir / "e2e.sqlite"),
            "result": str(run_dir / "result.json"),
            "log": str(run_dir / "run.log"),
        },
    }


def provider_summary(settings: Settings) -> dict[str, object]:
    return {
        "base_url_host": urlparse(settings.llm_base_url).hostname,
        "provider_type": settings.llm_provider_name,
        "model_name": settings.llm_model,
        "real_llm_enabled": settings.enable_real_llm,
        "timeline_llm_enabled": settings.timeline_llm_enabled,
    }


def validate_provider(settings: Settings) -> None:
    name = settings.llm_provider_name.lower()
    if settings.fake_pipeline_demo or any(
        word in name for word in ("mock", "fake", "test", "demo")
    ):
        raise AcceptanceFailure(
            "narrative", "MOCK_OR_FALLBACK_PROVIDER", "Mock/fallback Provider refused"
        )
    if not settings.enable_real_llm or not settings.timeline_llm_enabled:
        raise AcceptanceFailure(
            "narrative", "PROVIDER_CONFIG", "Real Narrative and Timeline LLMs must be enabled"
        )
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        raise AcceptanceFailure(
            "narrative", "PROVIDER_CONFIG", "Provider credential is not configured"
        )


def mark_after_failure(result: dict[str, Any], failed_stage: str) -> None:
    passed_failure = False
    for stage in STAGES:
        if stage == failed_stage:
            passed_failure = True
            continue
        if passed_failure and result["stage_status"][stage] == "NOT_STARTED":
            result["stage_status"][stage] = "SKIPPED_AFTER_FAILURE"


def summarize_narrative_modes(
    windows: list[Any], agent_runs: list[Any]
) -> dict[str, dict[str, object]]:
    """Return source-free diagnostics from persisted Narrative windows and AgentRuns."""

    attempts_by_mode: dict[str, list[Any]] = {}
    for agent_run in agent_runs:
        payload = getattr(agent_run, "payload", {})
        context = payload.get("input_context", {}) if isinstance(payload, dict) else {}
        mode = context.get("mode") if isinstance(context, dict) else None
        if isinstance(mode, str):
            attempts_by_mode.setdefault(mode, []).append(agent_run)

    summaries: dict[str, dict[str, object]] = {}
    for window in windows:
        mode = str(window.mode)
        attempts = attempts_by_mode.get(mode, [])
        field_paths: set[str] = set()
        for attempt in attempts:
            provider_result = getattr(attempt, "provider_result", None)
            execution = getattr(provider_result, "execution_metadata", None)
            diagnostics = getattr(execution, "schema_diagnostics", None)
            if isinstance(diagnostics, dict):
                values = diagnostics.get("schema_error_field_paths", [])
                if isinstance(values, list):
                    field_paths.update(value for value in values if isinstance(value, str))
        summaries[mode] = {
            "status": str(window.status),
            "agent_run_ids": [attempt.agent_run_id for attempt in attempts],
            "provider_request_count": int(window.provider_request_count),
            "attempt_count": int(window.attempt_count),
            "failure_category": window.failure_category,
            "finish_reason": window.provider_finish_reason,
            "completion_tokens": window.provider_completion_tokens,
            "schema_error_field_paths": sorted(field_paths),
        }
    return summaries


def record_narrative_diagnostics(
    result: dict[str, Any], windows: list[Any], agent_runs: list[Any]
) -> str | None:
    """Populate the acceptance result and return the first terminal mode category."""

    result["narrative_modes"] = summarize_narrative_modes(windows, agent_runs)
    result["provider_calls"]["narrative"] = sum(
        int(window.provider_request_count) for window in windows
    )
    result["counts"].update(
        narrative_requested_modes=len(windows),
        narrative_successful_modes=sum(str(window.status) == "SUCCEEDED" for window in windows),
        narrative_failed_modes=sum(str(window.status) != "SUCCEEDED" for window in windows),
        narrative_attempts=sum(int(window.attempt_count) for window in windows),
    )
    return next(
        (
            str(window.failure_category)
            for window in windows
            if str(window.status) != "SUCCEEDED" and window.failure_category
        ),
        None,
    )


def run_stage(result: dict[str, Any], stage: str, operation: Callable[[], Any]) -> Any:
    result["stage_status"][stage] = "RUNNING"
    try:
        value = operation()
    except Exception:
        result["stage_status"][stage] = "FAIL"
        raise
    result["stage_status"][stage] = "PASS"
    return value


def validate_scene_panel_lineage(
    scenes: list[Any], panels: list[Any], storybible: Any, timeline: Any
) -> None:
    event_ids, evidence = (
        set(timeline.event_ids),
        {
            json.dumps(x.model_dump(mode="json"), sort_keys=True)
            for x in storybible.evidence_refs + timeline.evidence_refs
        },
    )
    persons = {x.profile_id for x in storybible.entities if str(x.entity_kind) == "PERSON"}
    states = {x.state_id: x for x in storybible.state_changes}
    scene_ids = {x.scene_id for x in scenes}
    for scene in scenes:
        if (
            scene.project_id != storybible.project_id
            or scene.storybible_bundle_id != storybible.bundle_id
            or scene.timeline_bundle_id != timeline.bundle_id
            or not set(scene.related_event_ids) <= event_ids
        ):
            raise AcceptanceFailure(
                "scene_validation", "LINEAGE_ESCAPE", "Scene escaped approved bundle lineage"
            )
        if any(
            json.dumps(x.model_dump(mode="json"), sort_keys=True) not in evidence
            for x in scene.evidence_refs
        ):
            raise AcceptanceFailure(
                "scene_validation",
                "EVIDENCE_UNIVERSE_ESCAPE",
                "Scene evidence escaped trusted universe",
            )
    by_scene = {x.scene_id: x for x in scenes}
    for panel in panels:
        scene = by_scene.get(panel.scene_id)
        if (
            scene is None
            or panel.scene_id not in scene_ids
            or panel.project_id != storybible.project_id
            or panel.storybible_bundle_id != storybible.bundle_id
            or panel.timeline_bundle_id != timeline.bundle_id
            or not set(panel.related_event_ids) <= set(scene.related_event_ids)
        ):
            raise AcceptanceFailure(
                "panel_validation", "LINEAGE_ESCAPE", "Panel escaped Scene lineage"
            )
        if not set(panel.character_ids) <= persons or not set(panel.character_state_ids) <= set(
            states
        ):
            raise AcceptanceFailure(
                "panel_validation",
                "STORYBIBLE_UNIVERSE_ESCAPE",
                "Panel escaped frozen StoryBible universe",
            )
        for character_id, action in panel.character_actions.items():
            allowed = {
                s.state.get("activity") for s in states.values() if s.profile_id == character_id
            }
            if action not in allowed:
                raise AcceptanceFailure(
                    "panel_validation", "STATE_ACTION_ESCAPE", "Panel action is not canonical"
                )


def preflight(args: argparse.Namespace, result: dict[str, Any], settings: Settings) -> None:
    source = args.input.resolve()
    if (
        not source.is_file()
        or source.suffix.lower() != ".txt"
        or not source.read_text(encoding="utf-8").strip()
    ):
        raise AcceptanceFailure(
            "document_import", "FIXTURE", "UTF-8 TXT fixture is missing or empty"
        )
    # App construction creates tables and wires production services without a request.
    app = create_app(
        database_url=f"sqlite+pysqlite:///{Path(result['artifact_paths']['database']).as_posix()}"
    )
    if app.state.storybible_curator is None or app.state.timeline_agent is None:
        raise AcceptanceFailure(
            "storybible_context", "WIRING", "Production service wiring is incomplete"
        )
    # Preflight only verifies the fixture and production wiring. Narrative / Timeline /
    # StoryBible / Comic Planning / Panel stages are NOT executed here, so they must
    # remain NOT_STARTED rather than being falsely reported as PASS.
    result["stage_status"]["document_import"] = "PASS"
    result["result"] = "PREFLIGHT_PASS"
    result["mock_or_fallback_used"] = False
    result["counts"]["fixture_chars"] = len(source.read_text(encoding="utf-8"))


def execute_real(args: argparse.Namespace, result: dict[str, Any], settings: Settings) -> None:
    validate_provider(settings)
    project_id = f"real-pipeline-acceptance-{uuid4().hex[:12]}"
    result["project_id"] = project_id
    app = create_app(
        database_url=f"sqlite+pysqlite:///{Path(result['artifact_paths']['database']).as_posix()}"
    )
    with TestClient(app) as client:
        source = args.input.resolve()
        result["stage_status"]["document_import"] = "RUNNING"
        with source.open("rb") as stream:
            response = client.post(
                f"/projects/{project_id}/pipeline-runs/import-and-analyze",
                data={
                    "project_name": "Current real pipeline acceptance",
                    "real_llm_requested": "true",
                    "narrative_modes": json.dumps(NARRATIVE_MODES),
                },
                files={"file": (source.name, stream, "text/plain")},
            )
        if response.status_code != 200:
            raise AcceptanceFailure(
                "document_import", "API", f"Import pipeline HTTP {response.status_code}"
            )
        started = response.json()
        result.update(
            document_id=started["document_id"], narrative_run_id=started["analysis_run_id"]
        )
        result["stage_status"]["document_import"] = "PASS"
        status = client.get(f"/pipeline-runs/{started['analysis_run_id']}").json()
        mapping = {
            "gate1": status.get("gate1"),
            "narrative": status.get("narrative"),
            "gate2": status.get("gate2"),
            "timeline": status.get("timeline"),
            "gate3": status.get("gate3"),
        }
        with app.state.session_factory() as session:
            analysis_repository = NarrativeAnalysisRepository(session)
            windows = analysis_repository.list_windows(started["analysis_run_id"])
            agent_runs = AgentRunRepository(session).list_agent_runs(project_id)
            narrative_failure = record_narrative_diagnostics(result, windows, agent_runs)
        if mapping["gate1"] != "APPROVED":
            result["stage_status"]["gate1"] = "FAIL"
            raise AcceptanceFailure("gate1", "GATE1", f"Gate 1 stopped: {mapping['gate1']}")
        result["stage_status"]["gate1"] = "PASS"
        result["stage_status"]["chunking"] = "PASS"
        if mapping["narrative"] != "SUCCEEDED":
            result["stage_status"]["narrative"] = "FAIL"
            raise AcceptanceFailure(
                "narrative",
                narrative_failure or "NARRATIVE_FAILED",
                f"Narrative pipeline stopped: {mapping}",
            )
        result["stage_status"]["narrative"] = "PASS"
        if mapping["gate2"] != "APPROVED":
            result["stage_status"]["gate2"] = "FAIL"
            raise AcceptanceFailure("gate2", "GATE2", f"Gate 2 stopped: {mapping['gate2']}")
        result["stage_status"]["gate2"] = "PASS"
        result["stage_status"]["timeline_adapter"] = "PASS"
        if mapping["timeline"] != "APPROVED":
            result["stage_status"]["timeline"] = "FAIL"
            raise AcceptanceFailure(
                "timeline", "TIMELINE", f"Timeline stopped: {mapping['timeline']}"
            )
        result["stage_status"]["timeline"] = "PASS"
        if mapping["gate3"] not in {"APPROVED", "NEEDS_HUMAN_REVIEW"}:
            result["stage_status"]["gate3"] = "FAIL"
            raise AcceptanceFailure("gate3", "GATE3", f"Gate 3 stopped: {mapping['gate3']}")
        result["stage_status"]["gate3"] = "PASS"
        if mapping["gate3"] == "NEEDS_HUMAN_REVIEW":
            if not args.auto_approve_review:
                result["stage_status"]["human_review"] = "BLOCKED_ON_HUMAN_REVIEW"
                raise AcceptanceFailure(
                    "human_review",
                    "HUMAN_REVIEW_REQUIRED",
                    "Gate 3 requires explicit human approval",
                )
            with app.state.session_factory() as session:
                narrative_run = NarrativeAnalysisRepository(session).get_run(
                    started["analysis_run_id"]
                )
                if narrative_run is None or narrative_run.review_gate2_route is None:
                    raise AcceptanceFailure("gate2", "LINEAGE", "Gate 2 route unavailable")
                gate2 = narrative_run.review_gate2_route.approved_proposal_bundle
                if gate2 is None:
                    raise AcceptanceFailure("gate2", "LINEAGE", "Gate 2 bundle unavailable")
                timeline_run = TimelineGate3Repository(session).get_by_bundle(
                    project_id, gate2.bundle_id
                )
                if timeline_run is None:
                    raise AcceptanceFailure("gate3", "LINEAGE", "Gate 3 run unavailable")
            reviewed = client.post(
                f"/projects/{project_id}/timeline-gate3/runs/{timeline_run.timeline_run_id}/review",
                json={"resolution": "APPROVE", "reviewer_id": "acceptance-runner"},
            )
            if reviewed.status_code != 200:
                raise AcceptanceFailure(
                    "human_review", "HUMAN_REVIEW", f"Review HTTP {reviewed.status_code}"
                )
            result["stage_status"]["human_review"] = "PASS"
            status = client.get(f"/pipeline-runs/{started['analysis_run_id']}").json()
        else:
            result["stage_status"]["human_review"] = "PASS"
        timeline_id = status.get("approved_timeline_bundle_id")
        if not timeline_id:
            raise AcceptanceFailure(
                "approved_timeline", "TIMELINE_NOT_APPROVED", "ApprovedTimelineBundleV1 unavailable"
            )
        result["approved_timeline_bundle_id"] = timeline_id
        result["stage_status"]["approved_timeline"] = "PASS"

    with app.state.session_factory() as session:
        narrative = NarrativeAnalysisRepository(session).get_run(result["narrative_run_id"])
        if narrative is None or narrative.review_gate2_route is None:
            raise AcceptanceFailure("gate2", "LINEAGE", "Persisted Gate 2 route unavailable")
        gate2_bundle = narrative.review_gate2_route.approved_proposal_bundle
        if gate2_bundle is None:
            raise AcceptanceFailure("gate2", "LINEAGE", "Persisted Gate 2 bundle unavailable")
        timeline_run = TimelineGate3Repository(session).get_by_bundle(
            project_id, gate2_bundle.bundle_id
        )
        if timeline_run is None or timeline_run.approved_timeline_bundle is None:
            raise AcceptanceFailure(
                "approved_timeline", "LINEAGE", "Persisted Timeline bundle unavailable"
            )
        timeline = timeline_run.approved_timeline_bundle
        result["counts"].update(
            event_count=len(timeline.event_ids),
            temporal_relation_count=len(timeline.temporal_relations),
            evidence_ref_count=len(timeline.evidence_refs),
        )
        context = run_stage(
            result,
            "storybible_context",
            lambda: StoryBibleProductionContextAdapter(session).build(
                project_id=project_id,
                gate2_approved_bundle_id=gate2_bundle.bundle_id,
                approved_timeline_bundle_id=timeline.bundle_id,
            ),
        )
        coordinator = StoryBibleProductionCoordinator(
            input_builder=StoryBibleProductionInputBuilder(session),
            run_repository=StoryBibleProductionRunRepository(session),
            curator=app.state.storybible_curator,
            output_normalizer=StoryBibleProductionOutputNormalizer(),
            agent_run_repository=AgentRunRepository(session),
            settings=settings,
        )
        production = run_stage(
            result,
            "storybible_curator",
            lambda: coordinator.run(
                project_id=project_id,
                gate2_approved_bundle_id=gate2_bundle.bundle_id,
                approved_timeline_bundle_id=timeline.bundle_id,
                model_identity=settings.storybible_model,
                real_llm_requested=True,
            ),
        )
        result["storybible_production_run_id"], result["curator_agent_run_id"] = (
            production.run_id,
            production.agent_run_id,
        )
        result["provider_calls"]["storybible_curator"] = production.provider_request_count
        if (
            production.status != StoryBibleProductionRunStatus.SUCCEEDED
            or production.curator_proposal is None
        ):
            message = production.error_message or "StoryBible production failed"
            if (
                "finish_reason=length" in message
                or "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT" in message
            ):
                result["previous_curator_length_failure"] = "REPRODUCED"
                raise AcceptanceFailure(
                    "storybible_curator", "PROVIDER_LENGTH_BEFORE_FINAL_CONTENT", message
                )
            raise AcceptanceFailure(
                "storybible_curator", str(production.failure_stage or "STORYBIBLE"), message
            )
        result["previous_curator_length_failure"] = "NOT_REPRODUCED_IN_THIS_RUN"
        result["stage_status"]["storybible_normalization"] = "PASS"
        proposal = production.curator_proposal
        review_context = StoryBibleReviewContextV1(
            review_id=stable_id("storybible-review", production.run_id),
            project_id=project_id,
            source_storybible_run_id=production.run_id,
            source_approved_timeline_bundle_id=timeline.bundle_id,
            canonical_snapshot=context.canonical_snapshot,
            canonical_snapshot_hash=context.canonical_storybible_snapshot_hash,
            proposal_hash=storybible_proposal_hash(proposal),
            reviewed_at=datetime.now(UTC),
        )
        review_result = run_stage(
            result,
            "storybible_review",
            lambda: StoryBibleReviewService(SourceRepository(session)).review(
                review_context,
                production_run=production,
                proposal=proposal,
                commit_plan=proposal.commit_plan,
                approved_timeline=timeline,
            ),
        )
        review = StoryBibleReviewRepository(session).save_review(review_context, review_result)
        result["storybible_review_run_id"] = review.review_id
        if str(review_result.decision) != "APPROVE":
            raise AcceptanceFailure(
                "storybible_review",
                "STORYBIBLE_REVIEW",
                f"StoryBible review decision: {review_result.decision}",
            )
        story_repo, review_repo = StoryBibleRepository(session), StoryBibleReviewRepository(session)
        frozen = run_stage(
            result,
            "storybible_freeze",
            lambda: StoryBibleFreezeService(
                review_repository=review_repo,
                storybible_repository=story_repo,
                commit_service=CommitService(SourceRepository(session)),
            ).freeze(review.review_id, production_run=production, approved_timeline=timeline),
        )
        result["stage_status"]["approved_storybible"] = "PASS"
        result["approved_storybible_bundle_id"], result["snapshot_hash"] = (
            frozen.bundle_id,
            frozen.snapshot_hash,
        )
        result["counts"].update(
            entities=len(frozen.entities),
            relationships=len(frozen.relationships),
            world_rules=len(frozen.world_rules),
            state_changes=len(frozen.state_changes),
            storybible_evidence_refs=len(frozen.evidence_refs),
            source_chunks_count=len(context.source_chunks),
            narrative_proposals_count=len(context.approved_entities)
            + len(context.approved_events)
            + len(context.approved_state_changes),
            event_reference_count=len(context.trusted_event_ids),
            evidence_reference_count=len(context.trusted_evidence_refs),
        )
        scenes = run_stage(
            result,
            "comic_planning",
            lambda: ComicPlanningService().plan(storybible=frozen, timeline=timeline),
        )
        panels = run_stage(
            result,
            "panel_planning",
            lambda: [
                PanelPlanningService().plan(scene=scene, storybible=frozen) for scene in scenes
            ],
        )
        validate_scene_panel_lineage(scenes, panels, frozen, timeline)
        result["stage_status"]["scene_validation"] = "PASS"
        result["stage_status"]["panel_validation"] = "PASS"
        result["scene_count"], result["panel_count"] = len(scenes), len(panels)
        result["result"], result["mock_or_fallback_used"] = "PASS", False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--auto-approve-review", action="store_true")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    args = parser.parse_args()
    run_dir = args.artifact_root.resolve() / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    result = initial_result(run_dir)
    settings = get_settings()
    lines = [
        "CURRENT REAL PIPELINE ACCEPTANCE",
        json.dumps(provider_summary(settings), ensure_ascii=False),
    ]
    exit_code = 0
    try:
        (preflight if args.preflight_only else execute_real)(args, result, settings)
    except Exception as exc:
        stage = (
            exc.stage
            if isinstance(exc, AcceptanceFailure)
            else next((s for s in STAGES if result["stage_status"][s] == "RUNNING"), "runner")
        )
        category = (
            exc.category
            if isinstance(exc, AcceptanceFailure)
            else ("SCHEMA_VALIDATION" if isinstance(exc, ValidationError) else "UNEXPECTED")
        )
        result.update(
            result="FAIL",
            failure_stage=stage,
            failure_category=category,
            exception_type=type(exc).__name__,
            sanitized_error=sanitize(exc, settings),
        )
        if stage in result["stage_status"]:
            result["stage_status"][stage] = "FAIL"
            mark_after_failure(result, stage)
        lines.append(f"FAIL stage={stage} category={category} error={result['sanitized_error']}")
        exit_code = 1
    finally:
        result_path = run_dir / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "run.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "result": result["result"],
                    "failure_stage": result["failure_stage"],
                    "artifact_directory": str(run_dir),
                    "provider": provider_summary(settings),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
