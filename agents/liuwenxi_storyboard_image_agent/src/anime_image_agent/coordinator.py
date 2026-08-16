from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .backend import (
    EncodeOutcome,
    FakePromptEncoder,
    ModelLock,
    QwenPromptEncoder,
    prepare_model,
    validate_gpu_node,
    wait_for_gpu_zero_release,
)
from .config import GPU_PAIRS, MODEL_ID, Settings
from .contracts import ImageErrorV1, QueueRecordV1
from .io_utils import ExclusiveFileLock, atomic_write_json, now
from .queue import QueueStore
from .telemetry import summarize as summarize_telemetry


class Coordinator:
    def __init__(self, settings: Settings, backend_name: str = "qwen") -> None:
        if backend_name not in {"qwen", "fake"}:
            raise ValueError(f"unsupported backend: {backend_name}")
        self.settings = settings
        self.backend_name = backend_name
        self.queue = QueueStore(settings)
        self.artifacts = ArtifactStore(settings)

    def run(self, *, drain: bool = False, max_waves: int | None = None) -> int:
        completed_waves = 0
        with ExclusiveFileLock(self.settings.coordinator_lock):
            model_lock = self._prepare_runtime()
            recovered = self._recover_running()
            self.queue.event(
                "coordinator_started",
                backend=self.backend_name,
                recovered=recovered,
            )
            try:
                while True:
                    self.queue.ingest()
                    ready = self.queue.ready_count()
                    if ready:
                        if self.settings.gather_seconds > 0:
                            time.sleep(self.settings.gather_seconds)
                            self.queue.ingest()
                        records = self.queue.select_wave(self.settings.wave_size)
                        if records:
                            self._process_wave(records, model_lock)
                            completed_waves += 1
                            if max_waves is not None and completed_waves >= max_waves:
                                break
                            continue
                    if drain and not self.queue.has_pending_work():
                        break
                    time.sleep(self.settings.poll_seconds)
            except KeyboardInterrupt:
                self.queue.event("coordinator_interrupted")
            finally:
                self.queue.event("coordinator_stopped", waves=completed_waves)
        return completed_waves

    def _prepare_runtime(self) -> ModelLock:
        self.settings.ensure_directories()
        if self.backend_name == "fake":
            return ModelLock(MODEL_ID, "fake-test", Path("."))
        gpus = validate_gpu_node(self.settings)
        self.queue.event("gpu_preflight_passed", gpus=gpus)
        return prepare_model(self.settings)

    def _recover_running(self) -> int:
        recovered = 0
        running_root = self.settings.queue_root / "running"
        for path in sorted(running_root.glob("*.json")):
            record = QueueRecordV1.model_validate_json(path.read_text(encoding="utf-8"))
            result = self.artifacts.load_committed_result(record)
            if result is not None:
                self.queue.complete(result)
            else:
                self.queue.retry_or_fail(
                    record.job.request_id,
                    ImageErrorV1(
                        code="WORKER_CRASH",
                        message="coordinator recovered a task left in running state",
                        retryable=True,
                    ),
                )
            recovered += 1
        return recovered

    def _process_wave(self, records: list[QueueRecordV1], model_lock: ModelLock) -> None:
        wave_id = _wave_id()
        scratch_wave = self.settings.wave_root / wave_id
        persistent_wave = self.settings.run_root / "waves" / wave_id
        embedding_root = scratch_wave / "embeddings"
        task_ready_root = scratch_wave / "tasks" / "ready"
        task_ready_root.mkdir(parents=True, exist_ok=True)
        persistent_wave.mkdir(parents=True, exist_ok=True)
        atomic_write_json(scratch_wave / "settings.json", self.settings.to_dict())
        started_at = now()
        wall_started = time.perf_counter()
        self.queue.event("wave_started", wave_id=wave_id, jobs=len(records))

        try:
            encoder = (
                FakePromptEncoder()
                if self.backend_name == "fake"
                else QwenPromptEncoder(model_lock)
            )
            outcome = encoder.encode(records, wave_id, embedding_root)
        except Exception as error:
            if self.backend_name == "qwen":
                gc.collect()
                try:
                    import torch

                    torch.cuda.empty_cache()
                except (ImportError, RuntimeError):
                    pass
            outcome = EncodeOutcome([], [], 0.0, 0.0, 0.0)
            encoding_error = ImageErrorV1(
                code="PROMPT_ENCODING_FAILED",
                message=f"{type(error).__name__}: {str(error)[:1800]}",
                retryable=True,
            )
            for record in records:
                self.queue.retry_or_fail(record.job.request_id, encoding_error)
            self._write_wave_summary(
                persistent_wave,
                wave_id,
                records,
                outcome,
                [],
                started_at,
                wall_started,
                fatal_error=encoding_error.model_dump(mode="json"),
            )
            self._clean_scratch_wave(scratch_wave)
            return

        for record, error in outcome.failures:
            self.queue.retry_or_fail(record.job.request_id, error)
        if self.backend_name == "qwen" and outcome.tasks:
            try:
                wait_for_gpu_zero_release(self.settings)
            except Exception as error:
                release_error = ImageErrorV1(
                    code="ENCODER_RELEASE_FAILED",
                    message=f"{type(error).__name__}: {str(error)[:1800]}",
                    retryable=True,
                )
                for task in outcome.tasks:
                    self.queue.retry_or_fail(task.request_id, release_error)
                self._write_wave_summary(
                    persistent_wave,
                    wave_id,
                    records,
                    outcome,
                    [],
                    started_at,
                    wall_started,
                    fatal_error=release_error.model_dump(mode="json"),
                )
                self._clean_scratch_wave(scratch_wave)
                return

        for task in outcome.tasks:
            atomic_write_json(task_ready_root / f"{task.request_id}.json", task)

        worker_results: list[dict[str, Any]] = []
        if outcome.tasks:
            worker_results = self._launch_workers(
                scratch_wave,
                persistent_wave,
                min(len(GPU_PAIRS), len(outcome.tasks)),
            )
        self._reconcile_wave(records)
        self._write_wave_summary(
            persistent_wave,
            wave_id,
            records,
            outcome,
            worker_results,
            started_at,
            wall_started,
        )
        self._clean_scratch_wave(scratch_wave)

    def _launch_workers(
        self,
        scratch_wave: Path,
        persistent_wave: Path,
        worker_count: int,
    ) -> list[dict[str, Any]]:
        monitor_process: subprocess.Popen[bytes] | None = None
        stop_file = persistent_wave / "monitor.stop"
        telemetry_path = persistent_wave / "telemetry.jsonl"
        if self.backend_name == "qwen":
            monitor_environment = _module_environment()
            monitor_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "anime_image_agent",
                    "internal-monitor",
                    "--output",
                    str(telemetry_path),
                    "--stop-file",
                    str(stop_file),
                ],
                env=monitor_environment,
            )

        processes: list[tuple[int, subprocess.Popen[bytes], Any]] = []
        for worker_index in range(worker_count):
            pair = GPU_PAIRS[worker_index]
            log_path = persistent_wave / f"worker-{worker_index}.log"
            log_stream = log_path.open("wb")
            environment = _module_environment()
            environment["CUDA_VISIBLE_DEVICES"] = f"{pair[0]},{pair[1]}"
            environment["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "anime_image_agent",
                    "internal-worker",
                    "--settings",
                    str(scratch_wave / "settings.json"),
                    "--wave-root",
                    str(scratch_wave),
                    "--worker-index",
                    str(worker_index),
                    "--backend",
                    self.backend_name,
                ],
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                env=environment,
            )
            processes.append((worker_index, process, log_stream))

        results: list[dict[str, Any]] = []
        for worker_index, process, log_stream in processes:
            return_code = process.wait()
            log_stream.close()
            results.append({"worker_index": worker_index, "return_code": return_code})
        if monitor_process is not None:
            stop_file.touch()
            try:
                monitor_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                monitor_process.terminate()
                monitor_process.wait(timeout=10)
        return results

    def _reconcile_wave(self, records: list[QueueRecordV1]) -> None:
        for original in records:
            status = self.queue.status(original.job.request_id, required=False)
            if status is None or status.state != "running" or status.record is None:
                continue
            committed = self.artifacts.load_committed_result(status.record)
            if committed is not None:
                self.queue.complete(committed)
            else:
                self.queue.retry_or_fail(
                    original.job.request_id,
                    ImageErrorV1(
                        code="WORKER_CRASH",
                        message="worker exited without a terminal result",
                        retryable=True,
                    ),
                )

    def _write_wave_summary(
        self,
        persistent_wave: Path,
        wave_id: str,
        records: list[QueueRecordV1],
        outcome: EncodeOutcome,
        worker_results: list[dict[str, Any]],
        started_at: Any,
        wall_started: float,
        fatal_error: dict[str, Any] | None = None,
    ) -> None:
        states: dict[str, int] = {}
        for record in records:
            status = self.queue.status(record.job.request_id, required=False)
            state = status.state if status is not None else "missing"
            states[state] = states.get(state, 0) + 1
        payload = {
            "schema_name": "WaveSummaryV1",
            "wave_id": wave_id,
            "backend": self.backend_name,
            "model_id": MODEL_ID,
            "jobs": len(records),
            "encoded_jobs": len(outcome.tasks),
            "encoding_failures": len(outcome.failures),
            "encoder_load_seconds": outcome.load_seconds,
            "encode_seconds": outcome.encode_seconds,
            "encoder_peak_vram_gib": outcome.peak_vram_gib,
            "worker_results": worker_results,
            "states": states,
            "telemetry": summarize_telemetry(persistent_wave / "telemetry.jsonl"),
            "fatal_error": fatal_error,
            "wall_seconds": round(time.perf_counter() - wall_started, 3),
            "started_at": started_at.isoformat(),
            "completed_at": now().isoformat(),
        }
        atomic_write_json(persistent_wave / "summary.json", payload)
        self.queue.event("wave_completed", wave_id=wave_id, states=states)

    def _clean_scratch_wave(self, scratch_wave: Path) -> None:
        root = self.settings.wave_root.resolve()
        target = scratch_wave.resolve()
        if target.parent != root:
            raise RuntimeError(f"refusing to clean unexpected wave path: {target}")
        shutil.rmtree(target, ignore_errors=True)


def _wave_id() -> str:
    timestamp = now().strftime("%Y%m%d-%H%M%S")
    return f"wave-{timestamp}-{uuid.uuid4().hex[:8]}"


def _module_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1])
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source_root if not existing else source_root + os.pathsep + existing
    return environment
