from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from .backend import ModelLock
from .config import MODEL_ID, Settings
from .contracts import ImageJobV1, ImageResultV1, job_sha256, load_job
from .scene_contracts import GenerationSpecV1, SceneJobV1, SceneResultV1, VisualPlanV1
from .scene_coordinator import SceneCoordinator
from .scene_store import SceneStore
from .upstream_contracts import (
    UpstreamSceneEnvelopeV1,
    envelope_sha256,
    map_envelope_to_scene_job,
)
from .coordinator import Coordinator
from .io_utils import atomic_write_json, now
from .queue import QueueStore
from .telemetry import monitor
from .worker import run_wave_worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anime-image-agent",
        description="Qwen-Image-2512 production ImageProvider for an eight-A40 node",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one ImageJobV1 JSON file")
    validate.add_argument("input", type=Path)
    validate.set_defaults(func=command_validate)

    submit = subparsers.add_parser("submit", help="submit one ImageJobV1 to the inbox")
    submit.add_argument("input", type=Path)
    submit.set_defaults(func=command_submit)

    status = subparsers.add_parser("status", help="show queue state and public result")
    status.add_argument("request_id")
    status.set_defaults(func=command_status)

    retry = subparsers.add_parser("retry", help="create a Review Gate 6 retry request")
    retry.add_argument("request_id", help="completed request to retry")
    retry.add_argument("--reason", required=True)
    retry.add_argument("--new-request-id")
    retry.set_defaults(func=command_retry)

    run = subparsers.add_parser("run", help="run the queue coordinator continuously")
    run.add_argument("--backend", choices=("qwen", "fake"), default="qwen")
    run.add_argument("--max-waves", type=positive_int)
    run.set_defaults(func=command_run)

    drain = subparsers.add_parser("drain", help="process existing tasks and exit when empty")
    drain.add_argument("--backend", choices=("qwen", "fake"), default="qwen")
    drain.add_argument("--max-waves", type=positive_int)
    drain.set_defaults(func=command_drain)

    schema = subparsers.add_parser("schema", help="export external and internal runtime JSON schemas")
    schema.add_argument("--output", type=Path, required=True)
    schema.set_defaults(func=command_schema)

    worker = subparsers.add_parser("internal-worker", help="internal use only")
    worker.add_argument("--settings", type=Path, required=True)
    worker.add_argument("--wave-root", type=Path, required=True)
    worker.add_argument("--worker-index", type=int, choices=range(4), required=True)
    worker.add_argument("--backend", choices=("qwen", "fake"), required=True)
    worker.set_defaults(func=command_internal_worker)

    telemetry = subparsers.add_parser("internal-monitor", help="internal use only")
    telemetry.add_argument("--output", type=Path, required=True)
    telemetry.add_argument("--stop-file", type=Path, required=True)
    telemetry.add_argument("--interval", type=float, default=1.0)
    telemetry.set_defaults(func=command_internal_monitor)

    serve = subparsers.add_parser("serve", help="serve the scene-generation HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--backend", choices=("qwen", "fake"), default="qwen")
    serve.set_defaults(func=command_serve)

    scene_drain = subparsers.add_parser("scene-drain", help="process queued scene jobs and exit")
    scene_drain.add_argument("--backend", choices=("qwen", "fake"), default="qwen")
    scene_drain.set_defaults(func=command_scene_drain)

    scene_submit = subparsers.add_parser(
        "scene-submit",
        help="submit one UpstreamSceneEnvelopeV1 JSON file through the internal operator CLI",
    )
    scene_submit.add_argument("input", type=Path)
    scene_submit.set_defaults(func=command_scene_submit)
    return parser


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def command_validate(args: argparse.Namespace) -> int:
    job = load_job(args.input)
    _print_json(
        {
            "valid": True,
            "schema_name": job.schema_name,
            "request_id": job.request_id,
            "job_sha256": job_sha256(job),
            "note": "token length is checked with the locked model tokenizer during encoding",
        }
    )
    return 0


def command_submit(args: argparse.Namespace) -> int:
    job = load_job(args.input)
    status = QueueStore(Settings.from_environment()).enqueue(job)
    _print_json(
        {
            "request_id": status.request_id,
            "state": status.state,
            "idempotent": status.state != "inbox",
        }
    )
    return 0


def command_status(args: argparse.Namespace) -> int:
    status = QueueStore(Settings.from_environment()).status(args.request_id)
    payload = {
        "request_id": status.request_id,
        "state": status.state,
        "attempt": status.record.attempt if status.record else None,
        "result": status.result.model_dump(mode="json") if status.result else None,
    }
    _print_json(payload)
    return 0


def command_retry(args: argparse.Namespace) -> int:
    settings = Settings.from_environment()
    queue = QueueStore(settings)
    original = queue.status(args.request_id)
    if original.state not in {"succeeded", "failed", "rejected"} or original.record is None:
        raise ValueError("Review Gate retry requires a terminal original request")
    new_request_id = args.new_request_id or _retry_request_id(args.request_id)
    job = original.record.job.model_copy(
        update={"request_id": new_request_id, "retry_of": args.request_id}
    )
    status = queue.enqueue(job)
    queue.event(
        "review_retry_requested",
        request_id=new_request_id,
        retry_of=args.request_id,
        reason=args.reason[:1024],
    )
    _print_json(
        {
            "request_id": status.request_id,
            "state": status.state,
            "retry_of": args.request_id,
        }
    )
    return 0


def command_run(args: argparse.Namespace) -> int:
    Coordinator(Settings.from_environment(), args.backend).run(max_waves=args.max_waves)
    return 0


def command_drain(args: argparse.Namespace) -> int:
    Coordinator(Settings.from_environment(), args.backend).run(
        drain=True,
        max_waves=args.max_waves,
    )
    return 0


def command_schema(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.output / "image-job-v1.schema.json", ImageJobV1.model_json_schema())
    atomic_write_json(args.output / "image-result-v1.schema.json", ImageResultV1.model_json_schema())
    atomic_write_json(args.output / "scene-job-v1.schema.json", SceneJobV1.model_json_schema())
    atomic_write_json(args.output / "visual-plan-v1.schema.json", VisualPlanV1.model_json_schema())
    atomic_write_json(args.output / "generation-spec-v1.schema.json", GenerationSpecV1.model_json_schema())
    atomic_write_json(args.output / "scene-result-v1.schema.json", SceneResultV1.model_json_schema())
    atomic_write_json(
        args.output / "upstream-scene-envelope-v1.schema.json",
        UpstreamSceneEnvelopeV1.model_json_schema(),
    )
    _print_json({"output": str(args.output), "schemas": 7})
    return 0


def command_internal_worker(args: argparse.Namespace) -> int:
    settings = Settings.from_file(args.settings)
    if args.backend == "fake":
        model_lock = ModelLock(MODEL_ID, "fake-test", Path("."))
    else:
        model_lock = ModelLock.load(settings.model_lock)
    run_wave_worker(
        settings,
        args.wave_root,
        args.worker_index,
        args.backend,
        model_lock,
    )
    return 0


def command_internal_monitor(args: argparse.Namespace) -> int:
    monitor(args.output, args.stop_file, args.interval)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(backend=args.backend), host=args.host, port=args.port)
    return 0


def command_scene_drain(args: argparse.Namespace) -> int:
    SceneCoordinator(Settings.from_environment(), backend=args.backend).run(drain=True)
    return 0


def command_scene_submit(args: argparse.Namespace) -> int:
    envelope = UpstreamSceneEnvelopeV1.model_validate_json(args.input.read_text(encoding="utf-8"))
    job = map_envelope_to_scene_job(envelope)
    snapshot, created = SceneStore(Settings.from_environment().scene_db).submit(
        job,
        request_sha256=envelope_sha256(envelope),
    )
    _print_json(
        {
            "request_id": job.request_id,
            "status": snapshot.status,
            "idempotent": not created,
        }
    )
    return 0


def _retry_request_id(original: str) -> str:
    timestamp = now().strftime("%Y%m%d%H%M%S%f")
    suffix = f"-retry-{timestamp}"
    candidate = original[: 128 - len(suffix)] + suffix
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", candidate):
        raise ValueError("original request_id cannot be converted to a retry request_id")
    return candidate


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (ValidationError, ValueError, FileNotFoundError, RuntimeError) as error:
        print(
            json.dumps(
                {"error_type": type(error).__name__, "error": str(error)[:2048]},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
