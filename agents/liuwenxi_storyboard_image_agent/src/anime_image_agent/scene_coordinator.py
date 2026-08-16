from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

from .assets import PresetAssetRepository
from .backend import validate_gpu_node
from .compiler import GenerationCompiler
from .config import PLANNER_MODEL_ID, Settings
from .io_utils import ExclusiveFileLock
from .planning import FakeVisualPlanner, QwenVisualPlanner, assemble_planning_context
from .scene_contracts import PanelJobStatus, SceneErrorV1, SceneJobStatus, VisualPlanV1
from .scene_generation import (
    FakeSceneGenerator,
    QwenImageEdit2509Adapter,
    SceneGenerator,
    generation_key,
    prepare_locked_model,
)
from .scene_store import SceneSnapshot, SceneStore


class SceneCoordinator:
    def __init__(
        self,
        settings: Settings,
        *,
        backend: str = "qwen",
        store: SceneStore | None = None,
        repository: PresetAssetRepository | None = None,
        generator: SceneGenerator | None = None,
    ) -> None:
        if backend not in {"qwen", "fake"}:
            raise ValueError(f"unsupported scene backend: {backend}")
        self.settings = settings
        self.backend = backend
        self.store = store or SceneStore(settings.scene_db)
        self.repository = repository or PresetAssetRepository(
            settings.asset_root, settings.scratch_root / "asset-cache"
        )
        self.generator = generator
        self._gpu_validated = backend == "fake"

    def run_once(self) -> int:
        candidates = self.store.list_by_status(
            {
                SceneJobStatus.SUBMITTED,
                SceneJobStatus.PLANNING,
                SceneJobStatus.CONDITIONING,
                SceneJobStatus.GENERATING,
            },
            limit=self.settings.scene_wave_size,
        )
        wave: list[SceneSnapshot] = []
        panel_count = 0
        for snapshot in candidates:
            count = len(snapshot.job.panels)
            if wave and panel_count + count > 32:
                break
            wave.append(snapshot)
            panel_count += count
        if not wave:
            return 0
        if not self._gpu_validated:
            validate_gpu_node(self.settings)
            self._gpu_validated = True
        contexts = {}
        planning_inputs: list[SceneSnapshot] = []
        specs_by_panel = {}
        panel_to_scene = {}
        for snapshot in wave:
            try:
                recoverable = all(
                    panel.visual_plan is not None and panel.generation_spec is not None
                    for panel in snapshot.panels
                )
                if recoverable and snapshot.status in {
                    SceneJobStatus.CONDITIONING,
                    SceneJobStatus.GENERATING,
                }:
                    for panel in snapshot.panels:
                        if panel.status == PanelJobStatus.SUCCEEDED:
                            continue
                        spec = panel.generation_spec
                        assert spec is not None
                        key = (snapshot.job.request_id, panel.panel_id)
                        specs_by_panel[key] = spec
                        panel_to_scene[key] = snapshot
                    continue
                self.store.set_scene_status(snapshot.job.request_id, SceneJobStatus.PLANNING)
                contexts[snapshot.job.request_id] = assemble_planning_context(snapshot.job, self.repository)
                planning_inputs.append(snapshot)
            except Exception as error:
                self._fail_scene(snapshot.job.request_id, "ASSET_RESOLUTION_FAILED", error)
        try:
            plans = self._plan_wave(planning_inputs, contexts)
        except Exception as error:
            planning_error = SceneErrorV1(
                code="PLANNING_FAILED",
                message=f"{type(error).__name__}: {str(error)[:1800]}",
                retryable=False,
            )
            plans = {snapshot.job.request_id: planning_error for snapshot in planning_inputs}
        for snapshot in planning_inputs:
            request_id = snapshot.job.request_id
            outcome = plans.get(request_id)
            if isinstance(outcome, SceneErrorV1) or outcome is None:
                error = outcome or SceneErrorV1(code="PLANNING_FAILED", message="planner returned no result")
                self.store.set_scene_status(request_id, SceneJobStatus.FAILED, error)
                for panel in snapshot.job.panels:
                    self.store.fail_panel(request_id, panel.panel_id, error, 0)
                continue
            try:
                for panel_plan in outcome.panels:
                    self.store.save_plan(request_id, panel_plan)
                specs = GenerationCompiler(self.repository).compile(snapshot.job, contexts[request_id], outcome)
                for spec in specs:
                    self.store.save_spec(request_id, spec)
                    specs_by_panel[(request_id, spec.panel_id)] = spec
                    panel_to_scene[(request_id, spec.panel_id)] = snapshot
                self.store.set_scene_status(request_id, SceneJobStatus.CONDITIONING)
            except Exception as error:
                self._fail_scene(request_id, "COMPILATION_FAILED", error)
        pending = dict(specs_by_panel)
        for attempt in range(1, self.settings.max_attempts + 1):
            if not pending:
                break
            specs = list(pending.values())
            output_roots = {}
            attempts = {}
            touched_scenes = set()
            for key, spec in pending.items():
                snapshot = panel_to_scene[key]
                root = (
                    self.settings.output_root
                    / "scene-jobs"
                    / snapshot.job.project_id
                    / snapshot.job.chapter_id
                    / snapshot.job.scene_id
                    / spec.panel_id
                    / snapshot.job.request_id
                    / f"attempt-{attempt:02d}"
                )
                task_key = generation_key(spec)
                output_roots[task_key] = root
                attempts[task_key] = attempt
                touched_scenes.add(snapshot.job.request_id)
            for request_id in touched_scenes:
                self.store.set_scene_status(request_id, SceneJobStatus.CONDITIONING)
            try:
                conditioned, condition_errors = self._generator().condition_wave(specs)
            except Exception as error:
                conditioned = []
                condition_errors = {
                    generation_key(spec): SceneErrorV1(
                        code="CONDITIONING_FAILED",
                        message=f"{type(error).__name__}: {str(error)[:1800]}",
                        retryable=True,
                    )
                    for spec in specs
                }
            generating_scenes = set()
            for task in conditioned:
                self.store.mark_generating(task.spec.request_id, task.spec.panel_id, attempt)
                generating_scenes.add(task.spec.request_id)
            for request_id in generating_scenes:
                self.store.set_scene_status(request_id, SceneJobStatus.GENERATING)
            results = dict(condition_errors)
            if conditioned:
                try:
                    results.update(
                        self._generator().generate_conditioned_wave(conditioned, output_roots, attempts)
                    )
                except Exception as error:
                    results.update(
                        {
                            generation_key(task.spec): SceneErrorV1(
                                code="GENERATION_FAILED",
                                message=f"{type(error).__name__}: {str(error)[:1800]}",
                                retryable=True,
                            )
                            for task in conditioned
                        }
                    )
            retry_pending = {}
            for key, spec in pending.items():
                request_id, panel_id = key
                result = results.get(generation_key(spec))
                if result is None:
                    result = SceneErrorV1(code="GENERATION_MISSING", message="generator returned no result", retryable=True)
                if isinstance(result, SceneErrorV1):
                    if result.retryable and attempt < self.settings.max_attempts:
                        retry_pending[key] = spec
                    else:
                        self.store.fail_panel(request_id, panel_id, result, attempt)
                else:
                    artifact, metadata = result
                    self.store.complete_panel(request_id, panel_id, artifact, metadata)
            pending = retry_pending
        for snapshot in wave:
            current = self.store.get(snapshot.job.request_id)
            if current.status not in {
                SceneJobStatus.SUCCEEDED,
                SceneJobStatus.PARTIAL_FAILED,
                SceneJobStatus.FAILED,
            }:
                self.store.reconcile_scene(snapshot.job.request_id)
        return len(wave)

    def _generator(self) -> SceneGenerator:
        if self.generator is None:
            self.generator = (
                FakeSceneGenerator()
                if self.backend == "fake"
                else QwenImageEdit2509Adapter(self.settings)
            )
        return self.generator

    def run(self, *, drain: bool = False, stop_event: threading.Event | None = None) -> int:
        waves = 0
        with ExclusiveFileLock(self.settings.scene_coordinator_lock):
            while stop_event is None or not stop_event.is_set():
                processed = self.run_once()
                waves += int(processed > 0)
                if drain and processed == 0:
                    break
                if processed == 0:
                    time.sleep(self.settings.poll_seconds)
        return waves

    def _plan_wave(self, snapshots, contexts):
        if not snapshots:
            return {}
        if self.backend == "fake":
            planner = FakeVisualPlanner()
            return {item.job.request_id: planner.plan(contexts[item.job.request_id]) for item in snapshots}
        planner_lock = prepare_locked_model(
            PLANNER_MODEL_ID, self.settings.planner_model_root, self.settings.hf_cache
        )
        context = mp.get_context("spawn")
        processes = []
        outputs = []
        for gpu_index, snapshot in enumerate(snapshots[:8]):
            output = self.settings.scratch_root / "scene-planning" / f"{snapshot.job.request_id}.json"
            output.unlink(missing_ok=True)
            process = context.Process(
                target=_planner_worker_entry,
                args=(
                    planner_lock.snapshot,
                    snapshot.job.model_dump(mode="json"),
                    str(self.settings.asset_root),
                    str(self.settings.scratch_root / "asset-cache"),
                    gpu_index,
                    str(output),
                ),
            )
            process.start()
            processes.append(process)
            outputs.append((snapshot.job.request_id, output))
        for process in processes:
            process.join()
        results = {}
        for (request_id, output), process in zip(outputs, processes, strict=True):
            if not output.is_file():
                results[request_id] = SceneErrorV1(
                    code="PLANNING_WORKER_CRASH",
                    message=f"planner worker exited with code {process.exitcode}",
                    retryable=False,
                )
                continue
            payload = json.loads(output.read_text(encoding="utf-8"))
            results[request_id] = (
                SceneErrorV1.model_validate(payload["error"])
                if "error" in payload
                else VisualPlanV1.model_validate(payload["plan"])
            )
        return results

    def _fail_scene(self, request_id: str, code: str, error: Exception) -> None:
        scene_error = SceneErrorV1(code=code, message=f"{type(error).__name__}: {str(error)[:1800]}")
        snapshot = self.store.get(request_id)
        for panel in snapshot.panels:
            if panel.status not in {PanelJobStatus.SUCCEEDED, PanelJobStatus.FAILED}:
                self.store.fail_panel(request_id, panel.panel_id, scene_error, 0)
        self.store.set_scene_status(request_id, SceneJobStatus.FAILED, scene_error)


def _planner_worker_entry(
    model_path: str,
    job_payload: dict,
    asset_root: str,
    cache_root: str,
    gpu_index: int,
    output_path: str,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    from .scene_contracts import SceneJobV1
    from .io_utils import atomic_write_json

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    planner = None
    try:
        job = SceneJobV1.model_validate(job_payload)
        repository = PresetAssetRepository(Path(asset_root), Path(cache_root))
        planning_context = assemble_planning_context(job, repository)
        planner = QwenVisualPlanner(Path(model_path), device="cuda:0")
        plan = planner.plan(planning_context)
        atomic_write_json(output, {"plan": plan.model_dump(mode="json")})
    except Exception as error:
        scene_error = SceneErrorV1(
            code="PLANNING_FAILED", message=f"{type(error).__name__}: {str(error)[:1800]}", retryable=False
        )
        atomic_write_json(output, {"error": scene_error.model_dump(mode="json")})
    finally:
        if planner is not None:
            planner.close()
