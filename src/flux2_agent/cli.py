from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from comic_agent.schemas.image_workflow import QueueItem

from .catalog import load_catalog, update_reference_metadata, write_catalog
from .models import StoryboardRequest, WorkflowJob
from .planning import build_plan, validate_storyboard_handoff
from .queueing import QUEUE_STATES, QueueStore, run_queue_worker
from .workflow import run_workflow


def load_job(path: Path) -> WorkflowJob:
    return WorkflowJob.model_validate_json(path.read_text(encoding="utf-8"))


def load_storyboard_request(path: Path) -> StoryboardRequest:
    return StoryboardRequest.model_validate_json(path.read_text(encoding="utf-8"))


def load_job_source(source: str) -> WorkflowJob:
    payload = (
        sys.stdin.read()
        if source == "-"
        else Path(source).read_text(encoding="utf-8")
    )
    return WorkflowJob.model_validate_json(payload)


def queue_summary(item: QueueItem) -> dict[str, object]:
    return {
        "queue_id": item.queue_id,
        "status": item.status,
        "priority": item.priority,
        "attempts": item.attempts,
        "enqueued_at": item.enqueued_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "worker_id": item.worker_id,
        "run_root": item.run_root,
        "error": item.error,
        "handoff_validated": item.handoff_validated,
    }


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def json_output(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flux2-agent",
        description="FLUX.2 reference workflow agent",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("catalog", help="rebuild the reference manifest")
    commands.add_parser("references", help="list verified reference images")
    reference_set = commands.add_parser(
        "reference-set",
        help="review and classify one immutable reference asset",
    )
    reference_set.add_argument("asset_id")
    reference_set.add_argument(
        "--status",
        choices=("candidate", "approved", "rejected"),
        required=True,
    )
    reference_set.add_argument("--entity-id")
    reference_set.add_argument(
        "--role",
        choices=(
            "character_identity",
            "character_outfit",
            "scene",
            "prop",
            "style",
            "composition",
            "continuity",
        ),
    )
    reference_set.add_argument("--variant", default="base")
    reference_set.add_argument("--canonical", action="store_true")
    reference_set.add_argument("--notes")

    validate = commands.add_parser("validate", help="validate a workflow job")
    validate.add_argument("job", type=Path)
    validate.add_argument(
        "--selection",
        type=Path,
        help="validate locked storyboard input and selected asset handles",
    )

    run = commands.add_parser("run", help="run or preview a workflow job")
    run.add_argument("job", type=Path)
    run.add_argument(
        "--selection",
        type=Path,
        help="validate locked storyboard input and selected asset handles",
    )
    run.add_argument("--output-root", type=Path)
    run.add_argument("--model-path", type=Path)
    run.add_argument("--offline", action="store_true")
    run.add_argument("--dry-run", action="store_true")

    queue = commands.add_parser("queue", help="manage the storyboard generation queue")
    queue.add_argument(
        "--root",
        type=Path,
        help="queue state root (default: <workspace>/queue)",
    )
    queue_commands = queue.add_subparsers(dest="queue_command", required=True)

    submit = queue_commands.add_parser(
        "submit",
        help="validate and enqueue a workflow job",
    )
    submit.add_argument("job", help="WorkflowJob JSON path, or - for stdin")
    submit.add_argument("--selection", type=Path, help="locked StoryboardRequest JSON")
    submit.add_argument("--priority", type=int, default=100, help="lower values run first")

    listing = queue_commands.add_parser("list", help="list queued jobs")
    listing.add_argument("--status", choices=QUEUE_STATES)

    status = queue_commands.add_parser("status", help="show one queued job")
    status.add_argument("queue_id")

    retry = queue_commands.add_parser("retry", help="move a failed job back to pending")
    retry.add_argument("queue_id")

    cancel = queue_commands.add_parser("cancel", help="cancel a pending job")
    cancel.add_argument("queue_id")

    queue_commands.add_parser("recover", help="return interrupted running jobs to pending")
    queue_commands.add_parser("schema", help="print the upstream WorkflowJob JSON schema")

    worker = queue_commands.add_parser("worker", help="process pending jobs on a GPU")
    worker.add_argument("--output-root", type=Path)
    worker.add_argument("--model-path", type=Path)
    worker.add_argument("--offline", action="store_true")
    worker.add_argument("--watch", action="store_true", help="keep polling for new jobs")
    worker.add_argument("--poll-interval", type=positive_float, default=2.0)
    worker.add_argument("--max-jobs", type=positive_int)
    worker.add_argument("--worker-id")
    worker.add_argument("--recover-running", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    workspace = args.workspace.resolve()
    try:
        if args.command == "catalog":
            destination = write_catalog(workspace)
            print(destination)
            return

        if args.command == "reference-set":
            catalog = update_reference_metadata(
                workspace,
                args.asset_id,
                lifecycle=args.status,
                entity_id=args.entity_id,
                intended_role=args.role,
                variant=args.variant,
                is_canonical=args.canonical,
                notes=args.notes,
            )
            reference = next(
                item for item in catalog.references if item.asset_id == args.asset_id
            )
            json_output(reference.model_dump(mode="json"))
            return

        if args.command == "queue":
            if args.queue_command == "schema":
                json_output(WorkflowJob.model_json_schema())
                return

            queue_root = (args.root or workspace / "queue").resolve()
            store = QueueStore(queue_root)
            if args.queue_command == "submit":
                job = load_job_source(args.job)
                handoff_validated = False
                if args.selection:
                    request = load_storyboard_request(args.selection.resolve())
                    validate_storyboard_handoff(request, job)
                    handoff_validated = True
                catalog = load_catalog(workspace)
                build_plan(workspace, job, catalog)
                item = store.enqueue(
                    job,
                    priority=args.priority,
                    handoff_validated=handoff_validated,
                )
                json_output(queue_summary(item))
                return
            if args.queue_command == "list":
                json_output(
                    [queue_summary(item) for item in store.list_items(args.status)]
                )
                return
            if args.queue_command == "status":
                item = store.get(args.queue_id)
                payload = item.model_dump(mode="json")
                payload["job"] = {
                    "job_id": item.job.job_id,
                    "source_script": item.job.source_script,
                    "shots": len(item.job.shots),
                }
                json_output(payload)
                return
            if args.queue_command == "retry":
                json_output(queue_summary(store.retry(args.queue_id)))
                return
            if args.queue_command == "cancel":
                json_output(queue_summary(store.cancel(args.queue_id)))
                return
            if args.queue_command == "recover":
                json_output(
                    [queue_summary(item) for item in store.recover_running()]
                )
                return
            if args.recover_running:
                store.recover_running()
            output_root = (args.output_root or workspace / "runs").resolve()
            completed = run_queue_worker(
                store,
                workspace,
                output_root,
                model_path=args.model_path,
                offline=args.offline,
                watch=args.watch,
                poll_interval=args.poll_interval,
                max_jobs=args.max_jobs,
                worker_id=args.worker_id,
                on_event=(
                    lambda item: print(
                        json.dumps(queue_summary(item), ensure_ascii=False),
                        flush=True,
                    )
                    if args.watch
                    else None
                ),
            )
            if not args.watch:
                json_output([queue_summary(item) for item in completed])
            return

        catalog = load_catalog(workspace)
        if args.command == "references":
            json_output(catalog.model_dump(mode="json"))
            return

        job = load_job(args.job.resolve())
        if args.selection:
            request = load_storyboard_request(args.selection.resolve())
            validate_storyboard_handoff(request, job)
        plan = build_plan(workspace, job, catalog)
        if args.command == "validate":
            json_output(
                {
                    "valid": True,
                    "job_id": job.job_id,
                    "selected_assets": len(job.selected_assets),
                    "shots": len(plan.shots),
                    "handoff_validated": bool(args.selection),
                }
            )
            return
        if args.dry_run:
            json_output(plan.model_dump(mode="json"))
            return

        output_root = (args.output_root or workspace / "runs").resolve()
        run_root = run_workflow(
            job,
            plan,
            output_root,
            model_path=args.model_path,
            offline=args.offline,
        )
        print(run_root)
    except (FileNotFoundError, KeyError, ValueError, ValidationError) as error:
        raise SystemExit(f"error: {error}") from error


if __name__ == "__main__":
    main()
