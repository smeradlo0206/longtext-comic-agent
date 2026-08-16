from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from .assets import PresetAssetRepository
from .backend import validate_gpu_node
from .config import Settings
from .scene_contracts import SceneJobStatus, TERMINAL_SCENE_STATUSES
from .scene_coordinator import SceneCoordinator
from .scene_store import SceneConflictError, SceneNotFoundError, SceneStore
from .upstream_contracts import (
    UpstreamSceneEnvelopeV1,
    envelope_sha256,
    map_envelope_to_scene_job,
)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: SceneJobStatus
    idempotent: bool
    status_url: str
    result_url: str


def create_app(
    settings: Settings | None = None,
    *,
    backend: str = "qwen",
    start_coordinator: bool = True,
    coordinator: SceneCoordinator | None = None,
) -> FastAPI:
    settings = settings or Settings.from_environment()
    settings.ensure_directories()
    store = coordinator.store if coordinator else SceneStore(settings.scene_db)
    repository = coordinator.repository if coordinator else PresetAssetRepository(
        settings.asset_root, settings.scratch_root / "asset-cache"
    )
    coordinator = coordinator or SceneCoordinator(
        settings, backend=backend, store=store, repository=repository
    )
    stop_event = threading.Event()
    worker_thread: threading.Thread | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal worker_thread
        if start_coordinator:
            worker_thread = threading.Thread(
                target=coordinator.run,
                kwargs={"stop_event": stop_event},
                name="scene-coordinator",
                daemon=True,
            )
            worker_thread.start()
        yield
        stop_event.set()
        if worker_thread is not None:
            worker_thread.join(timeout=max(5.0, settings.poll_seconds * 2))

    app = FastAPI(
        title="Qwen Comic Image Agent",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.repository = repository
    app.state.coordinator = coordinator
    app.state.backend = backend

    @app.post(
        "/v1/scene-jobs",
        response_model=SubmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_scene(envelope: UpstreamSceneEnvelopeV1) -> SubmissionResponse:
        job = map_envelope_to_scene_job(envelope)
        try:
            repository.get_profile(job.asset_profile_id)
            for panel in job.panels:
                for character in panel.characters:
                    repository.get_character(job.asset_profile_id, character.character_id)
            snapshot, created = store.submit(
                job,
                request_sha256=envelope_sha256(envelope),
            )
        except SceneConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (FileNotFoundError, KeyError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return SubmissionResponse(
            request_id=job.request_id,
            status=snapshot.status,
            idempotent=not created,
            status_url=f"/v1/scene-jobs/{job.request_id}",
            result_url=f"/v1/scene-jobs/{job.request_id}/result",
        )

    @app.get("/v1/scene-jobs/{request_id}")
    def get_scene_status(request_id: str) -> dict:
        try:
            snapshot = store.get(request_id)
        except SceneNotFoundError as error:
            raise HTTPException(status_code=404, detail="scene job not found") from error
        return {
            "request_id": request_id,
            "status": snapshot.status,
            "panels": [
                {
                    "panel_id": panel.panel_id,
                    "status": panel.status,
                    "error": panel.error.model_dump(mode="json") if panel.error else None,
                }
                for panel in snapshot.panels
            ],
            "submitted_at": snapshot.submitted_at,
            "completed_at": snapshot.completed_at,
            "error": snapshot.error.model_dump(mode="json") if snapshot.error else None,
        }

    @app.get("/v1/scene-jobs/{request_id}/result")
    def get_scene_result(request_id: str) -> Response:
        try:
            result = store.result(request_id)
        except SceneNotFoundError as error:
            raise HTTPException(status_code=404, detail="scene job not found") from error
        payload = result.model_dump(mode="json")
        if result.status not in TERMINAL_SCENE_STATUSES:
            return JSONResponse(payload, status_code=status.HTTP_202_ACCEPTED)
        return JSONResponse(payload)

    @app.get("/v1/artifacts/{image_id}", response_class=FileResponse)
    def get_artifact(image_id: str) -> FileResponse:
        try:
            artifact = store.artifact_by_id(image_id)
        except SceneNotFoundError as error:
            raise HTTPException(status_code=404, detail="artifact not found") from error
        path = Path(artifact.uri)
        if not path.is_file() or path.resolve() != path:
            raise HTTPException(status_code=404, detail="artifact file not found")
        return FileResponse(path, media_type=artifact.mime_type, filename=f"{image_id}.png")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    def ready() -> Response:
        checks: dict[str, object] = {}
        try:
            store.ping()
            checks["database"] = "ok"
        except Exception as error:
            checks["database"] = f"failed: {error}"
        profile_dirs = [path.name for path in settings.asset_root.iterdir() if path.is_dir()] if settings.asset_root.is_dir() else []
        try:
            if not profile_dirs:
                raise FileNotFoundError("no preset asset profiles")
            for profile_id in profile_dirs:
                repository.validate_profile(profile_id)
            checks["assets"] = "ok"
        except Exception as error:
            checks["assets"] = f"failed: {error}"
        if backend == "fake":
            checks["models"] = "fake"
            checks["gpus"] = "fake"
        else:
            planner_lock = settings.planner_model_root / "model-lock.json"
            edit_lock = settings.edit_model_root / "model-lock.json"
            checks["models"] = "ok" if planner_lock.is_file() and edit_lock.is_file() else "model locks missing"
            try:
                validate_gpu_node(settings)
                checks["gpus"] = "ok"
            except Exception as error:
                checks["gpus"] = f"failed: {error}"
        if start_coordinator:
            checks["coordinator"] = "ok" if worker_thread is not None and worker_thread.is_alive() else "stopped"
        healthy = all(value in {"ok", "fake"} for value in checks.values())
        return JSONResponse(
            {"status": "ready" if healthy else "not_ready", "checks": checks},
            status_code=200 if healthy else 503,
        )

    return app
