from __future__ import annotations

import json
import os
import socket
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from comic_agent.schemas.image_workflow import QueueAttempt, QueueItem, QueueStatus

from .backend import Flux2Backend
from .catalog import load_catalog
from .locking import exclusive_lock
from .models import WorkflowJob
from .planning import build_plan
from .workflow import run_workflow

QUEUE_STATES: tuple[QueueStatus, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class QueueStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        for state in QUEUE_STATES:
            state_root = self.root / state
            state_root.mkdir(exist_ok=True)
            state_root.chmod(0o700)
        self.lock_path = self.root / ".queue.lock"
        self.lock_path.touch(exist_ok=True)
        self.lock_path.chmod(0o600)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with exclusive_lock(self.lock_path):
            yield

    def _path(self, state: QueueStatus, queue_id: str) -> Path:
        return self.root / state / f"{queue_id}.json"

    def _find_path(self, queue_id: str) -> Path | None:
        matches = [
            path
            for state in QUEUE_STATES
            if (path := self._path(state, queue_id)).is_file()
        ]
        if len(matches) > 1:
            raise RuntimeError(f"queue item exists in multiple states: {queue_id}")
        return matches[0] if matches else None

    def _read(self, path: Path) -> QueueItem:
        return QueueItem.model_validate_json(path.read_text(encoding="utf-8"))

    def _repair_transitions(self) -> None:
        for state in QUEUE_STATES:
            for path in list((self.root / state).glob("*.json")):
                item = self._read(path)
                if item.status == state:
                    continue
                destination = self._path(item.status, item.queue_id)
                if destination.exists():
                    raise RuntimeError(
                        f"cannot repair duplicate queue item: {item.queue_id}"
                    )
                path.replace(destination)

    def _write(self, path: Path, item: QueueItem) -> None:
        temporary = self.root / f".{item.queue_id}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)

    def enqueue(
        self,
        job: WorkflowJob,
        *,
        priority: int = 100,
        handoff_validated: bool = False,
    ) -> QueueItem:
        now = utc_now()
        item = QueueItem(
            queue_id=job.job_id,
            status="pending",
            priority=priority,
            enqueued_at=now,
            updated_at=now,
            handoff_validated=handoff_validated,
            job=job,
        )
        with self._locked():
            self._repair_transitions()
            if self._find_path(item.queue_id):
                raise ValueError(f"queue item already exists: {item.queue_id}")
            self._write(self._path("pending", item.queue_id), item)
        return item

    def get(self, queue_id: str) -> QueueItem:
        with self._locked():
            self._repair_transitions()
            path = self._find_path(queue_id)
            if path is None:
                raise KeyError(f"queue item not found: {queue_id}")
            return self._read(path)

    def list_items(self, status: QueueStatus | None = None) -> list[QueueItem]:
        states = (status,) if status else QUEUE_STATES
        with self._locked():
            self._repair_transitions()
            items = [
                self._read(path)
                for state in states
                for path in (self.root / state).glob("*.json")
            ]
        return sorted(
            items,
            key=lambda item: (
                QUEUE_STATES.index(item.status),
                item.priority,
                item.enqueued_at,
                item.queue_id,
            ),
        )

    def claim_next(self, worker_id: str) -> QueueItem | None:
        with self._locked():
            self._repair_transitions()
            pending = [
                self._read(path) for path in (self.root / "pending").glob("*.json")
            ]
            if not pending:
                return None
            item = min(
                pending,
                key=lambda candidate: (
                    candidate.priority,
                    candidate.enqueued_at,
                    candidate.queue_id,
                ),
            )
            source = self._path("pending", item.queue_id)
            destination = self._path("running", item.queue_id)
            now = utc_now()
            claimed = item.model_copy(
                update={
                    "status": "running",
                    "updated_at": now,
                    "claimed_at": now,
                    "completed_at": None,
                    "worker_id": worker_id,
                    "attempts": item.attempts + 1,
                    "run_root": None,
                    "error": None,
                }
            )
            self._write(source, claimed)
            source.replace(destination)
            return claimed

    def _finish(
        self,
        item: QueueItem,
        *,
        status: Literal["succeeded", "failed"],
        run_root: Path | None = None,
        error: str | None = None,
    ) -> QueueItem:
        with self._locked():
            self._repair_transitions()
            running_path = self._path("running", item.queue_id)
            if not running_path.is_file():
                raise ValueError(f"queue item is not running: {item.queue_id}")
            current = self._read(running_path)
            now = utc_now()
            attempt = QueueAttempt(
                attempt=current.attempts,
                worker_id=current.worker_id or "unknown",
                status=status,
                started_at=current.claimed_at or now,
                completed_at=now,
                run_root=str(run_root.resolve()) if run_root else None,
                error=error,
            )
            finished = current.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "completed_at": now,
                    "run_root": attempt.run_root,
                    "error": error,
                    "history": [*current.history, attempt],
                }
            )
            self._write(running_path, finished)
            running_path.replace(self._path(status, item.queue_id))
            return finished

    def succeed(self, item: QueueItem, run_root: Path) -> QueueItem:
        return self._finish(item, status="succeeded", run_root=run_root)

    def fail(self, item: QueueItem, error: Exception | str) -> QueueItem:
        message = (
            str(error)
            if isinstance(error, str)
            else f"{type(error).__name__}: {error}"
        )
        return self._finish(item, status="failed", error=message[:4000])

    def retry(self, queue_id: str) -> QueueItem:
        with self._locked():
            self._repair_transitions()
            source = self._path("failed", queue_id)
            if not source.is_file():
                raise ValueError(f"queue item is not failed: {queue_id}")
            item = self._read(source)
            now = utc_now()
            pending = item.model_copy(
                update={
                    "status": "pending",
                    "updated_at": now,
                    "claimed_at": None,
                    "completed_at": None,
                    "worker_id": None,
                    "run_root": None,
                    "error": None,
                }
            )
            self._write(source, pending)
            source.replace(self._path("pending", queue_id))
            return pending

    def cancel(self, queue_id: str) -> QueueItem:
        with self._locked():
            self._repair_transitions()
            source = self._path("pending", queue_id)
            if not source.is_file():
                raise ValueError(f"queue item is not pending: {queue_id}")
            item = self._read(source)
            now = utc_now()
            cancelled = item.model_copy(
                update={
                    "status": "cancelled",
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._write(source, cancelled)
            source.replace(self._path("cancelled", queue_id))
            return cancelled

    def recover_running(self) -> list[QueueItem]:
        recovered: list[QueueItem] = []
        with self._locked():
            self._repair_transitions()
            for source in sorted((self.root / "running").glob("*.json")):
                item = self._read(source)
                now = utc_now()
                attempt = QueueAttempt(
                    attempt=item.attempts,
                    worker_id=item.worker_id or "unknown",
                    status="interrupted",
                    started_at=item.claimed_at or now,
                    completed_at=now,
                    error="recovered after worker interruption",
                )
                pending = item.model_copy(
                    update={
                        "status": "pending",
                        "updated_at": now,
                        "claimed_at": None,
                        "completed_at": None,
                        "worker_id": None,
                        "run_root": None,
                        "error": None,
                        "history": [*item.history, attempt],
                    }
                )
                self._write(source, pending)
                source.replace(self._path("pending", item.queue_id))
                recovered.append(pending)
        return recovered


def run_queue_worker(
    store: QueueStore,
    workspace: Path,
    output_root: Path,
    *,
    model_path: Path | None = None,
    offline: bool = False,
    watch: bool = False,
    poll_interval: float = 2.0,
    max_jobs: int | None = None,
    worker_id: str | None = None,
    on_event: Callable[[QueueItem], None] | None = None,
) -> list[QueueItem]:
    workspace = workspace.resolve()
    output_root = output_root.resolve()
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    completed: list[QueueItem] = []
    backend: Flux2Backend | None = None
    backend_key: tuple[str, str, str] | None = None

    try:
        while max_jobs is None or len(completed) < max_jobs:
            item = store.claim_next(worker_id)
            if item is None:
                if not watch:
                    break
                time.sleep(poll_interval)
                continue

            if on_event:
                on_event(item)
            try:
                queue_wait_seconds = (
                    (item.claimed_at - item.enqueued_at).total_seconds()
                    if item.claimed_at is not None
                    else 0.0
                )
                catalog = load_catalog(workspace)
                plan = build_plan(workspace, item.job, catalog)
                source = (
                    str(model_path.resolve())
                    if model_path
                    else item.job.generation.model_id
                )
                key = (source, item.job.generation.device, item.job.generation.dtype)
                model_load_seconds = 0.0
                backend_reused = backend is not None and backend_key == key
                if backend is None or backend_key != key:
                    if backend is not None:
                        backend.close()
                    backend = Flux2Backend(
                        item.job.generation,
                        model_path=model_path,
                        offline=offline,
                    )
                    load_started = time.perf_counter()
                    backend.load()
                    model_load_seconds = time.perf_counter() - load_started
                    backend_reused = False
                    backend_key = key
                backend.settings = item.job.generation
                run_root = run_workflow(
                    item.job,
                    plan,
                    output_root,
                    model_path=model_path,
                    offline=offline,
                    backend=backend,
                    model_load_seconds=model_load_seconds,
                    backend_reused=backend_reused,
                    queue_wait_seconds=queue_wait_seconds,
                )
                result = store.succeed(item, run_root)
            except Exception as error:
                result = store.fail(item, error)
            completed.append(result)
            if on_event:
                on_event(result)
    finally:
        if backend is not None:
            backend.close()

    return completed
