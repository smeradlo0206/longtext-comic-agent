"""Command-line entrypoint for the end-to-end long-text comic workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    ComicProductionRunV1,
)
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.review_gate1_service import ReviewGate1Service, build_review_gate1_input
from flux2_agent.queueing import QueueStore, run_queue_worker


def _path_in_workspace(workspace: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (workspace / value).resolve()


def _project(project_id: str, name: str) -> ProjectSpecV1:
    return ProjectSpecV1(
        id=project_id,
        name=name,
        project_type=ProjectType.LONG_NOVEL,
        fidelity_mode=FidelityMode.CANON_STRICT,
        output_format="PAGES",
        reading_direction="LTR",
        allow_new_events=False,
        allow_new_dialogue=False,
        allow_event_reordering=False,
        allow_visual_compression=True,
        allow_dialogue_splitting=True,
        require_source_traceability=True,
        max_auto_repairs=3,
        budget_limit=None,
    )


def _load_request(path: Path, document_id: str) -> ComicProductionRequestV1:
    payload = json.loads(path.read_text(encoding="utf-8"))
    configured = payload.get("document_id")
    if configured not in {None, "AUTO", document_id}:
        raise ValueError("request document_id does not match the imported source")
    payload["document_id"] = document_id
    return ComicProductionRequestV1.model_validate(payload)


def _load_panel_plans(path: Path) -> list[PanelPlanV1]:
    plans = TypeAdapter(list[PanelPlanV1]).validate_json(path.read_text(encoding="utf-8"))
    if not plans:
        raise ValueError("panel plan file must contain at least one panel")
    return plans


def _repositories(database_path: Path):  # type: ignore[no-untyped-def]
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    return engine, session, SourceRepository(session), ComicProductionRepository(session)


def _run_summary(run: ComicProductionRunV1) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "status": str(run.status),
        "document_id": run.document_id,
        "queue_id": run.queue_id,
        "run_root": run.run_root,
        "panel_count": len(run.manifest.proposal.panels),
        "identity_anchor_count": len(run.manifest.workflow_job.identity_anchors),
        "pages": [artifact.file for artifact in run.page_artifacts],
        "performance": (
            run.performance.model_dump(mode="json") if run.performance else None
        ),
        "error": run.error,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comic-agent")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path("runs/comic-agent.sqlite"))
    parser.add_argument("--queue-root", type=Path, default=Path("queue/comic"))
    parser.add_argument("--run-root", type=Path, default=Path("runs"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="import TXT, compile panels, and run local FLUX.2")
    run.add_argument("source", type=Path)
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--project-id", default="local-longtext-comic")
    run.add_argument("--project-name", default="Local long-text comic")
    run.add_argument("--priority", type=int, default=100)
    run.add_argument("--model-path", type=Path, default=Path("models/FLUX.2-klein-4B"))
    run.add_argument("--offline", action="store_true")
    run.add_argument("--compile-only", action="store_true")

    planned = subparsers.add_parser(
        "run-planned",
        help="import TXT and render provider-neutral PanelPlan records with local FLUX.2",
    )
    planned.add_argument("source", type=Path)
    planned.add_argument("--panels", type=Path, required=True)
    planned.add_argument("--request", type=Path, required=True)
    planned.add_argument("--project-name", default="Planned long-text comic")
    planned.add_argument("--priority", type=int, default=100)
    planned.add_argument(
        "--model-path", type=Path, default=Path("models/FLUX.2-klein-4B")
    )
    planned.add_argument("--offline", action="store_true")
    planned.add_argument("--compile-only", action="store_true")

    status = subparsers.add_parser("status", help="refresh one compiled production run")
    status.add_argument("run_id")

    worker = subparsers.add_parser("worker", help="drain compiled image workflows")
    worker.add_argument("--model-path", type=Path, default=Path("models/FLUX.2-klein-4B"))
    worker.add_argument("--offline", action="store_true")
    worker.add_argument("--max-jobs", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace = args.workspace.resolve()
    database_path = _path_in_workspace(workspace, args.database)
    queue_root = _path_in_workspace(workspace, args.queue_root)
    run_root = _path_in_workspace(workspace, args.run_root)
    engine, session, source_repository, production_repository = _repositories(database_path)
    queue_store = QueueStore(queue_root)
    coordinator = ComicProductionCoordinator(
        workspace=workspace,
        source_repository=source_repository,
        production_repository=production_repository,
        queue_store=queue_store,
    )
    try:
        if args.command == "status":
            print(
                json.dumps(
                    _run_summary(coordinator.refresh(args.run_id)),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.command == "worker":
            completed = run_queue_worker(
                queue_store,
                workspace,
                run_root,
                model_path=args.model_path,
                offline=args.offline,
                max_jobs=args.max_jobs,
            )
            print(
                json.dumps(
                    [
                        {
                            "queue_id": item.queue_id,
                            "status": item.status,
                            "run_root": item.run_root,
                            "error": item.error,
                        }
                        for item in completed
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        source_path = args.source.resolve()
        text = source_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("source TXT is empty")
        panel_plans = (
            _load_panel_plans(args.panels.resolve())
            if args.command == "run-planned"
            else None
        )
        project_id = panel_plans[0].project_id if panel_plans else args.project_id
        source_repository.create_project(_project(project_id, args.project_name))
        parsed = DocumentParser().parse_txt(
            project_id=project_id,
            filename=source_path.name,
            text=text,
            storage_uri=source_path.as_uri(),
        )
        gate1 = ReviewGate1Service().review(
            build_review_gate1_input(parsed=parsed, normalized_text=text)
        )
        if str(gate1.decision) != "APPROVED":
            raise ValueError(f"source review Gate 1 blocked import: {gate1.decision}")
        imported = source_repository.import_reviewed_document(parsed, gate1)
        request = _load_request(args.request.resolve(), imported.document.document_id)
        if panel_plans is not None:
            run = coordinator.compile_planned_and_enqueue(
                project_id=project_id,
                request=request,
                panel_plans=panel_plans,
                priority=args.priority,
            )
        else:
            run = coordinator.compile_and_enqueue(
                project_id=project_id,
                request=request,
                priority=args.priority,
            )
        if not args.compile_only and str(run.status) not in {"SUCCEEDED", "RUNNING"}:
            run_queue_worker(
                queue_store,
                workspace,
                run_root,
                model_path=args.model_path,
                offline=args.offline,
                max_jobs=1,
            )
            run = coordinator.refresh(run.run_id)
        print(json.dumps(_run_summary(run), ensure_ascii=False, indent=2))
    except (FileNotFoundError, KeyError, ValueError, ValidationError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
