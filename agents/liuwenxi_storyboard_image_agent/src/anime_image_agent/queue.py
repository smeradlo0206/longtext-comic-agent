from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from .config import Settings
from .contracts import (
    ImageErrorV1,
    ImageJobV1,
    ImageResultV1,
    QueueRecordV1,
    ResultStatus,
    job_sha256,
)
from .io_utils import append_jsonl, atomic_write_json, load_json, now


QUEUE_STATES = ("inbox", "ready", "running", "succeeded", "failed", "rejected")
TERMINAL_STATES = ("succeeded", "failed", "rejected")


class QueueConflictError(ValueError):
    pass


class QueueItemNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class QueueStatus:
    request_id: str
    state: str
    record: QueueRecordV1 | None
    result: ImageResultV1 | None


class QueueStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.queue_root
        self.ids_root = self.root / "ids"
        self.invalid_root = self.root / "invalid"
        self.ensure_directories()

    def ensure_directories(self) -> None:
        self.settings.ensure_directories()
        self.ids_root.mkdir(parents=True, exist_ok=True)
        self.invalid_root.mkdir(parents=True, exist_ok=True)
        for state in QUEUE_STATES:
            (self.root / state).mkdir(parents=True, exist_ok=True)

    def state_path(self, state: str, request_id: str) -> Path:
        if state not in QUEUE_STATES:
            raise ValueError(f"unknown queue state: {state}")
        return self.root / state / f"{request_id}.json"

    def result_path(self, request_id: str) -> Path:
        return self.settings.result_root / f"{request_id}.json"

    def event(self, event: str, **fields: object) -> None:
        append_jsonl(
            self.settings.event_log,
            {"timestamp": now().isoformat(), "event": event, **fields},
        )

    def _register_id(self, request_id: str, digest: str) -> bool:
        path = self.ids_root / f"{request_id}.json"
        payload = (json.dumps({"request_id": request_id, "job_sha256": digest}) + "\n").encode(
            "utf-8"
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            existing: dict[str, object] | None = None
            for _ in range(20):
                try:
                    existing = load_json(path)
                    break
                except (json.JSONDecodeError, OSError, ValueError):
                    time.sleep(0.01)
            if existing is None:
                raise QueueConflictError(f"request registration is incomplete: {request_id}")
            if existing.get("job_sha256") != digest:
                raise QueueConflictError(
                    f"request_id {request_id!r} already exists with different content"
                )
            return False
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def enqueue(self, job: ImageJobV1) -> QueueStatus:
        digest = job_sha256(job)
        is_new = self._register_id(job.request_id, digest)
        existing = self.status(job.request_id, required=False)
        if existing is not None:
            if existing.record and existing.record.job_sha256 != digest:
                raise QueueConflictError(
                    f"request_id {job.request_id!r} already exists with different content"
                )
            self.event("submission_idempotent", request_id=job.request_id, state=existing.state)
            return existing

        timestamp = now()
        record = QueueRecordV1(
            job=job,
            job_sha256=digest,
            attempt=1,
            submitted_at=timestamp,
            updated_at=timestamp,
        )
        atomic_write_json(self.state_path("inbox", job.request_id), record)
        self.event("submitted", request_id=job.request_id, new_registration=is_new)
        return QueueStatus(job.request_id, "inbox", record, None)

    def ingest(self) -> tuple[int, int]:
        accepted = 0
        rejected = 0
        for source in sorted((self.root / "inbox").glob("*.json")):
            try:
                payload = load_json(source)
                if payload.get("schema_name") == "QueueRecordV1":
                    record = QueueRecordV1.model_validate(payload)
                    self._register_id(record.job.request_id, record.job_sha256)
                else:
                    job = ImageJobV1.model_validate(payload)
                    digest = job_sha256(job)
                    self._register_id(job.request_id, digest)
                    timestamp = now()
                    record = QueueRecordV1(
                        job=job,
                        job_sha256=digest,
                        submitted_at=timestamp,
                        updated_at=timestamp,
                    )
                existing = self._locate_outside_inbox(record.job.request_id)
                if existing is not None:
                    existing_state, existing_path = existing
                    existing_record = QueueRecordV1.model_validate_json(
                        existing_path.read_text(encoding="utf-8")
                    )
                    if existing_record.job_sha256 != record.job_sha256:
                        raise QueueConflictError(
                            f"request_id {record.job.request_id!r} has conflicting queue content"
                        )
                    source.unlink(missing_ok=True)
                    accepted += 1
                    self.event(
                        "submission_idempotent",
                        request_id=record.job.request_id,
                        state=existing_state,
                    )
                    continue
                destination = self.state_path("ready", record.job.request_id)
                if destination.exists():
                    source.unlink(missing_ok=True)
                else:
                    atomic_write_json(source, record)
                    os.replace(source, destination)
                accepted += 1
                self.event("ready", request_id=record.job.request_id)
            except (ValidationError, ValueError, OSError, json.JSONDecodeError) as error:
                destination = self.invalid_root / f"{source.stem}.{int(time.time() * 1000)}.json"
                try:
                    os.replace(source, destination)
                except FileNotFoundError:
                    continue
                atomic_write_json(
                    destination.with_suffix(".error.json"),
                    {
                        "code": "INVALID_INPUT",
                        "message": str(error)[:2048],
                        "source": str(destination),
                        "rejected_at": now().isoformat(),
                    },
                )
                rejected += 1
                self.event("input_rejected", source=source.name, error_type=type(error).__name__)
        return accepted, rejected

    def _locate_outside_inbox(self, request_id: str) -> tuple[str, Path] | None:
        for state in (*TERMINAL_STATES, "running", "ready"):
            path = self.state_path(state, request_id)
            if path.is_file():
                return state, path
        return None

    def locate(self, request_id: str) -> tuple[str, Path] | None:
        for state in (*TERMINAL_STATES, "running", "ready", "inbox"):
            path = self.state_path(state, request_id)
            if path.is_file():
                return state, path
        return None

    def status(self, request_id: str, *, required: bool = True) -> QueueStatus | None:
        located = self.locate(request_id)
        result_path = self.result_path(request_id)
        result = None
        if result_path.is_file():
            result = ImageResultV1.model_validate_json(result_path.read_text(encoding="utf-8"))
        if located is None:
            if result is not None:
                state = result.status.value.lower()
                return QueueStatus(request_id, state, None, result)
            if required:
                raise QueueItemNotFoundError(request_id)
            return None
        state, path = located
        record = QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))
        return QueueStatus(request_id, state, record, result)

    def ready_count(self) -> int:
        return sum(1 for _ in (self.root / "ready").glob("*.json"))

    def select_wave(self, limit: int) -> list[QueueRecordV1]:
        candidates: list[tuple[int, datetime, str, Path, QueueRecordV1]] = []
        for path in (self.root / "ready").glob("*.json"):
            try:
                record = QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, OSError):
                continue
            candidates.append(
                (
                    record.job.sequence_no,
                    record.submitted_at,
                    record.job.request_id,
                    path,
                    record,
                )
            )
        selected: list[QueueRecordV1] = []
        for _, _, request_id, source, record in sorted(candidates)[:limit]:
            destination = self.state_path("running", request_id)
            try:
                os.replace(source, destination)
            except FileNotFoundError:
                continue
            selected.append(record)
            self.event("wave_selected", request_id=request_id, attempt=record.attempt)
        return selected

    def load_running(self, request_id: str) -> QueueRecordV1:
        path = self.state_path("running", request_id)
        if not path.is_file():
            raise QueueItemNotFoundError(f"running request not found: {request_id}")
        return QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))

    def write_result(self, result: ImageResultV1) -> None:
        path = self.result_path(result.request_id)
        if path.is_file():
            existing = ImageResultV1.model_validate_json(path.read_text(encoding="utf-8"))
            if existing != result:
                raise QueueConflictError(f"result already exists for {result.request_id}")
            return
        atomic_write_json(path, result)

    def complete(self, result: ImageResultV1) -> None:
        self.write_result(result)
        source = self.state_path("running", result.request_id)
        if result.status == ResultStatus.SUCCEEDED:
            state = "succeeded"
        elif result.status == ResultStatus.REJECTED:
            state = "rejected"
        else:
            state = "failed"
        destination = self.state_path(state, result.request_id)
        if source.exists():
            os.replace(source, destination)
        elif not destination.exists():
            raise QueueItemNotFoundError(f"cannot finalize missing request: {result.request_id}")
        self.event(
            "completed",
            request_id=result.request_id,
            status=result.status.value,
            attempts=result.attempts,
        )

    def retry_or_fail(
        self,
        request_id: str,
        error: ImageErrorV1,
        *,
        terminal_result: ImageResultV1 | None = None,
    ) -> bool:
        record = self.load_running(request_id)
        if error.retryable and record.attempt < self.settings.max_attempts:
            updated = record.model_copy(
                update={
                    "attempt": record.attempt + 1,
                    "updated_at": now(),
                    "last_error": error,
                }
            )
            running = self.state_path("running", request_id)
            atomic_write_json(running, updated)
            os.replace(running, self.state_path("ready", request_id))
            self.event(
                "retry_scheduled",
                request_id=request_id,
                next_attempt=updated.attempt,
                error_code=error.code,
            )
            return True
        if terminal_result is None:
            terminal_result = failure_result(record, error)
        self.complete(terminal_result)
        return False

    def recover_running(self) -> int:
        recovered = 0
        for path in sorted((self.root / "running").glob("*.json")):
            record = QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))
            result_path = self.result_path(record.job.request_id)
            if result_path.is_file():
                result = ImageResultV1.model_validate_json(result_path.read_text(encoding="utf-8"))
                self.complete(result)
            else:
                error = ImageErrorV1(
                    code="WORKER_CRASH",
                    message="coordinator recovered a task left in running state",
                    retryable=True,
                )
                self.retry_or_fail(record.job.request_id, error)
            recovered += 1
        return recovered

    def has_pending_work(self) -> bool:
        return any(
            any((self.root / state).glob("*.json"))
            for state in ("inbox", "ready", "running")
        )

    def records(self, states: Iterable[str] = QUEUE_STATES) -> Iterable[QueueRecordV1]:
        for state in states:
            for path in sorted((self.root / state).glob("*.json")):
                yield QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))


def failure_result(record: QueueRecordV1, error: ImageErrorV1) -> ImageResultV1:
    job = record.job
    status = ResultStatus.FAILED if error.retryable else ResultStatus.REJECTED
    return ImageResultV1(
        request_id=job.request_id,
        project_id=job.project_id,
        chapter_id=job.chapter_id,
        scene_id=job.scene_id,
        panel_id=job.panel_id,
        sequence_no=job.sequence_no,
        status=status,
        attempts=record.attempt,
        error=error,
        completed_at=now(),
    )
