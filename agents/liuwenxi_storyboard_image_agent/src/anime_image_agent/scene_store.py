from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .io_utils import now
from .scene_contracts import (
    GenerationSpecV1,
    PanelArtifactV1,
    PanelGenerationMetadataV1,
    PanelGenerationResultV1,
    PanelJobStatus,
    PanelVisualPlanV1,
    SceneErrorV1,
    SceneJobStatus,
    SceneJobV1,
    SceneResultV1,
    TERMINAL_SCENE_STATUSES,
    scene_job_sha256,
)


class SceneConflictError(ValueError):
    pass


class SceneNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    job: SceneJobV1
    status: SceneJobStatus
    request_sha256: str
    submitted_at: str
    completed_at: str | None
    error: SceneErrorV1 | None
    panels: tuple[PanelGenerationResultV1, ...]


class SceneStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS scene_jobs (
                    request_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_json TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS panel_jobs (
                    request_id TEXT NOT NULL,
                    panel_id TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    visual_plan_json TEXT,
                    generation_spec_json TEXT,
                    artifact_json TEXT,
                    metadata_json TEXT,
                    error_json TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(request_id, panel_id),
                    FOREIGN KEY(request_id) REFERENCES scene_jobs(request_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS panel_jobs_status_idx ON panel_jobs(status, request_id);
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    panel_id TEXT,
                    event TEXT NOT NULL,
                    fields_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def ping(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def submit(
        self,
        job: SceneJobV1,
        *,
        request_sha256: str | None = None,
    ) -> tuple[SceneSnapshot, bool]:
        digest = request_sha256 or scene_job_sha256(job)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("request_sha256 must be a lowercase SHA-256 digest")
        timestamp = now().isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT request_sha256 FROM scene_jobs WHERE request_id = ?", (job.request_id,)
            ).fetchone()
            if row is not None:
                if row["request_sha256"] != digest:
                    raise SceneConflictError(f"request_id {job.request_id!r} exists with different content")
                return self._snapshot(connection, job.request_id), False
            connection.execute(
                "INSERT INTO scene_jobs VALUES (?, ?, ?, ?, NULL, ?, ?, NULL)",
                (
                    job.request_id,
                    digest,
                    job.model_dump_json(),
                    SceneJobStatus.SUBMITTED.value,
                    timestamp,
                    timestamp,
                ),
            )
            for panel in job.panels:
                connection.execute(
                    "INSERT INTO panel_jobs(request_id,panel_id,sequence_no,status,updated_at) VALUES(?,?,?,?,?)",
                    (job.request_id, panel.panel_id, panel.sequence_no, PanelJobStatus.SUBMITTED.value, timestamp),
                )
            self._event(connection, job.request_id, None, "submitted", {})
            return self._snapshot(connection, job.request_id), True

    def get(self, request_id: str) -> SceneSnapshot:
        with self._connect() as connection:
            return self._snapshot(connection, request_id)

    def list_by_status(self, statuses: set[SceneJobStatus], limit: int = 8) -> list[SceneSnapshot]:
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT request_id FROM scene_jobs WHERE status IN ({placeholders}) ORDER BY submitted_at LIMIT ?",
                (*[item.value for item in statuses], limit),
            ).fetchall()
            return [self._snapshot(connection, row["request_id"]) for row in rows]

    def set_scene_status(
        self,
        request_id: str,
        status: SceneJobStatus,
        error: SceneErrorV1 | None = None,
    ) -> None:
        timestamp = now().isoformat()
        completed = timestamp if status in TERMINAL_SCENE_STATUSES else None
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE scene_jobs SET status=?,error_json=?,updated_at=?,completed_at=COALESCE(?,completed_at) WHERE request_id=?",
                (status.value, _dump(error), timestamp, completed, request_id),
            ).rowcount
            if not changed:
                raise SceneNotFoundError(request_id)
            self._event(connection, request_id, None, "scene_status", {"status": status.value})

    def save_plan(self, request_id: str, plan: PanelVisualPlanV1) -> None:
        self._update_panel(
            request_id,
            plan.panel_id,
            PanelJobStatus.PLANNED,
            visual_plan_json=plan.model_dump_json(),
        )

    def save_spec(self, request_id: str, spec: GenerationSpecV1) -> None:
        self._update_panel(
            request_id,
            spec.panel_id,
            PanelJobStatus.CONDITIONED,
            generation_spec_json=spec.model_dump_json(),
        )

    def mark_generating(self, request_id: str, panel_id: str, attempt: int) -> None:
        self._update_panel(request_id, panel_id, PanelJobStatus.GENERATING, attempt=attempt)

    def complete_panel(
        self,
        request_id: str,
        panel_id: str,
        artifact: PanelArtifactV1,
        metadata: PanelGenerationMetadataV1,
    ) -> None:
        self._update_panel(
            request_id,
            panel_id,
            PanelJobStatus.SUCCEEDED,
            artifact_json=artifact.model_dump_json(),
            metadata_json=metadata.model_dump_json(),
            error_json=None,
        )

    def fail_panel(self, request_id: str, panel_id: str, error: SceneErrorV1, attempt: int) -> None:
        self._update_panel(
            request_id,
            panel_id,
            PanelJobStatus.FAILED,
            error_json=error.model_dump_json(),
            attempt=attempt,
        )

    def result(self, request_id: str) -> SceneResultV1:
        snapshot = self.get(request_id)
        return SceneResultV1(
            request_id=snapshot.job.request_id,
            project_id=snapshot.job.project_id,
            chapter_id=snapshot.job.chapter_id,
            scene_id=snapshot.job.scene_id,
            status=snapshot.status,
            panels=list(snapshot.panels),
            submitted_at=snapshot.submitted_at,
            completed_at=snapshot.completed_at,
        )

    def artifact_by_id(self, image_id: str) -> PanelArtifactV1:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT artifact_json FROM panel_jobs WHERE artifact_json IS NOT NULL"
            ).fetchall()
        for row in rows:
            artifact = PanelArtifactV1.model_validate_json(row["artifact_json"])
            if artifact.image_id == image_id:
                return artifact
        raise SceneNotFoundError(image_id)

    def reconcile_scene(self, request_id: str) -> SceneJobStatus:
        snapshot = self.get(request_id)
        successes = sum(panel.status == PanelJobStatus.SUCCEEDED for panel in snapshot.panels)
        failures = sum(panel.status == PanelJobStatus.FAILED for panel in snapshot.panels)
        if successes + failures != len(snapshot.panels):
            return snapshot.status
        if successes == len(snapshot.panels):
            status = SceneJobStatus.SUCCEEDED
        elif successes:
            status = SceneJobStatus.PARTIAL_FAILED
        else:
            status = SceneJobStatus.FAILED
        self.set_scene_status(request_id, status)
        return status

    def _update_panel(self, request_id: str, panel_id: str, status: PanelJobStatus, **fields: object) -> None:
        timestamp = now().isoformat()
        assignments = ["status=?", "updated_at=?"]
        values: list[object] = [status.value, timestamp]
        allowed = {
            "visual_plan_json",
            "generation_spec_json",
            "artifact_json",
            "metadata_json",
            "error_json",
            "attempt",
        }
        for field, value in fields.items():
            if field not in allowed:
                raise ValueError(f"unsupported panel field: {field}")
            assignments.append(f"{field}=?")
            values.append(value)
        values.extend((request_id, panel_id))
        with self._transaction() as connection:
            changed = connection.execute(
                f"UPDATE panel_jobs SET {','.join(assignments)} WHERE request_id=? AND panel_id=?",
                values,
            ).rowcount
            if not changed:
                raise SceneNotFoundError(f"{request_id}/{panel_id}")
            self._event(connection, request_id, panel_id, "panel_status", {"status": status.value})

    def _snapshot(self, connection: sqlite3.Connection, request_id: str) -> SceneSnapshot:
        scene = connection.execute("SELECT * FROM scene_jobs WHERE request_id=?", (request_id,)).fetchone()
        if scene is None:
            raise SceneNotFoundError(request_id)
        job = SceneJobV1.model_validate_json(scene["request_json"])
        rows = connection.execute(
            "SELECT * FROM panel_jobs WHERE request_id=? ORDER BY sequence_no", (request_id,)
        ).fetchall()
        panels = tuple(
            PanelGenerationResultV1(
                panel_id=row["panel_id"],
                status=PanelJobStatus(row["status"]),
                visual_plan=_load(PanelVisualPlanV1, row["visual_plan_json"]),
                generation_spec=_load(GenerationSpecV1, row["generation_spec_json"]),
                artifact=_load(PanelArtifactV1, row["artifact_json"]),
                metadata=_load(PanelGenerationMetadataV1, row["metadata_json"]),
                error=_load(SceneErrorV1, row["error_json"]),
            )
            for row in rows
        )
        return SceneSnapshot(
            job=job,
            status=SceneJobStatus(scene["status"]),
            request_sha256=scene["request_sha256"],
            submitted_at=scene["submitted_at"],
            completed_at=scene["completed_at"],
            error=_load(SceneErrorV1, scene["error_json"]),
            panels=panels,
        )

    def _event(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        panel_id: str | None,
        event: str,
        fields: dict[str, object],
    ) -> None:
        connection.execute(
            "INSERT INTO workflow_events(request_id,panel_id,event,fields_json,created_at) VALUES(?,?,?,?,?)",
            (request_id, panel_id, event, json.dumps(fields, ensure_ascii=False), now().isoformat()),
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()


def _dump(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json()
    return json.dumps(value, ensure_ascii=False)


def _load(model, value: str | None):
    return None if value is None else model.model_validate_json(value)
