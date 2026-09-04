from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any

from PIL import Image

from comic_agent.services.visual_qa import PanelVisualQA

from .backend import Flux2Backend
from .models import ContinuityCrop, PlannedShot, WorkflowJob, WorkflowPlan


def utc_now() -> datetime:
    return datetime.now(UTC)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.touch(mode=0o600, exist_ok=True)
    temporary.chmod(0o600)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    path.chmod(0o600)


def create_run_directory(output_root: Path, job_id: str) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    candidate = output_root.resolve() / f"{job_id}-{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = output_root.resolve() / f"{job_id}-{stamp}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, mode=0o700)
    candidate.chmod(0o700)
    return candidate


def copy_reference_images(run_root: Path, plan: WorkflowPlan) -> list[dict[str, str]]:
    copied: dict[str, dict[str, str]] = {}
    references = [
        *[anchor.source_reference for anchor in plan.identity_anchors],
        *[reference for shot in plan.shots for reference in shot.references],
    ]
    for reference in references:
        if reference.asset_id in copied:
            continue
        destination = (
            run_root
            / f"reference-{reference.asset_id}{reference.path.suffix.lower()}"
        )
        shutil.copy2(reference.path, destination)
        destination.chmod(0o600)
        copied[reference.asset_id] = {
            "asset_id": reference.asset_id,
            "file": destination.name,
        }
    return list(copied.values())


def apply_identity_anchor_paths(
    shot: PlannedShot,
    anchor_paths_by_entity: dict[str, Path],
) -> PlannedShot:
    """Replace character inputs with this run's normalized color anchors."""

    references = [
        reference.model_copy(
            update={"path": anchor_paths_by_entity.get(reference.entity_id, reference.path)}
        )
        if reference.role in {"character_identity", "character_outfit"}
        else reference
        for reference in shot.references
    ]
    return shot.model_copy(update={"references": references})


def create_contact_sheet(
    run_root: Path,
    output_names: list[str],
    *,
    columns: int,
    filename: str,
) -> dict[str, int | str]:
    images = []
    try:
        for output_name in output_names:
            with Image.open(run_root / output_name) as source:
                images.append(source.convert("RGB"))
        if not images:
            raise ValueError("a contact sheet requires at least one generated image")
        width, height = images[0].size
        if any(image.size != (width, height) for image in images):
            raise ValueError("contact sheet images must share one size")
        rows = ceil(len(images) / columns)
        canvas = Image.new("RGB", (width * columns, height * rows), "white")
        try:
            for index, image in enumerate(images):
                canvas.paste(image, ((index % columns) * width, (index // columns) * height))
            destination = run_root / filename
            canvas.save(destination, format="PNG", optimize=True)
            destination.chmod(0o600)
        finally:
            canvas.close()
    finally:
        for image in images:
            image.close()
    return {
        "file": filename,
        "columns": columns,
        "rows": rows,
        "width": width * columns,
        "height": height * rows,
    }


def prepare_continuity_reference(
    run_root: Path,
    parent_path: Path,
    child_shot_id: str,
    crop: ContinuityCrop | None,
) -> Path:
    if crop is None:
        return parent_path

    destination = run_root / f"continuity-{parent_path.stem}-for-{child_shot_id}.png"
    with Image.open(parent_path) as source:
        width, height = source.size
        box = (
            round(crop.left * width),
            round(crop.top * height),
            round(crop.right * width),
            round(crop.bottom * height),
        )
        cropped = source.convert("RGB").crop(box)
        try:
            cropped.save(destination, format="PNG", optimize=True)
        finally:
            cropped.close()
    destination.chmod(0o600)
    return destination


def run_workflow(
    job: WorkflowJob,
    plan: WorkflowPlan,
    output_root: Path,
    *,
    model_path: Path | None = None,
    offline: bool = False,
    backend: Flux2Backend | None = None,
    qa_service: PanelVisualQA | None = None,
    model_load_seconds: float | None = None,
    backend_reused: bool | None = None,
    queue_wait_seconds: float = 0.0,
) -> Path:
    workflow_started = time.perf_counter()
    run_root = create_run_directory(output_root, job.job_id)
    write_json(run_root / "request.json", job.model_dump(mode="json"))
    write_json(run_root / "plan.json", plan.model_dump(mode="json"))
    anchor_id_by_entity = {
        anchor.entity_id: anchor.anchor_id for anchor in plan.identity_anchors
    }
    result: dict[str, Any] = {
        "schema_version": "2.2",
        "job_id": job.job_id,
        "status": "running",
        "model_id": job.generation.model_id,
        "model_source": str(model_path.resolve()) if model_path else job.generation.model_id,
        "started_at": utc_now().isoformat(),
        "execution_order": plan.execution_order,
        "performance": {
            "latency_budget_seconds": job.visual_qa.latency_budget_seconds,
            "queue_wait_seconds": round(max(0.0, queue_wait_seconds), 3),
            "backend_reused": backend_reused if backend_reused is not None else backend is not None,
            "stages": {
                "setup": round(time.perf_counter() - workflow_started, 3),
                "reference_copy": 0.0,
                "model_load": round(model_load_seconds or 0.0, 3),
                "identity_anchor_generation": 0.0,
                "panel_generation": 0.0,
                "visual_qa": 0.0,
                "selective_repair_generation": 0.0,
                "contact_sheet": 0.0,
                "page_composition": 0.0,
                "lettering": 0.0,
            },
            "workflow_seconds": None,
            "end_to_end_seconds": None,
            "single_image_seconds": None,
            "within_budget": None,
            "workflow_within_budget": None,
        },
        "references": [],
        "identity_anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "slot": anchor.slot,
                "asset_id": anchor.asset_id,
                "entity_id": anchor.entity_id,
                "width": anchor.width,
                "height": anchor.height,
                "status": "pending",
                "attempts": [],
                "qa_history": [],
                "repairs": [],
            }
            for anchor in plan.identity_anchors
        ],
        "shots": [
            {
                "shot_id": shot.shot_id,
                "reference_bindings": [
                    {
                        "image_index": reference.image_index,
                        "slot": reference.slot,
                        "asset_id": reference.asset_id,
                        "entity_id": reference.entity_id,
                        "role": reference.role,
                        "identity_anchor_id": anchor_id_by_entity.get(
                            reference.entity_id
                        ),
                    }
                    for reference in shot.references
                ],
                "continuity": (
                    {
                        "from_shot": shot.continuity_from,
                        "image_index": shot.continuity_image_index,
                        "crop": (
                            shot.continuity_crop.model_dump(mode="json")
                            if shot.continuity_crop
                            else None
                        ),
                    }
                    if shot.continuity_from
                    else None
                ),
                "status": "pending",
                "attempts": [],
                "qa_history": [],
                "repairs": [],
            }
            for shot in plan.shots
        ],
    }
    write_json(run_root / "result.json", result)

    stages = result["performance"]["stages"]
    local_backend = backend is None
    active_backend = backend or Flux2Backend(
        job.generation,
        model_path=model_path,
        offline=offline,
    )
    qa_service = qa_service or PanelVisualQA()

    def finish_performance() -> None:
        workflow_seconds = time.perf_counter() - workflow_started
        external_model_load = float(model_load_seconds or 0.0) if backend is not None else 0.0
        end_to_end_seconds = (
            workflow_seconds + external_model_load + max(0.0, queue_wait_seconds)
        )
        shot_seconds = [
            sum(float(attempt["seconds"]) for attempt in record["attempts"])
            for record in result["shots"]
        ]
        panel_count = max(1, len(result["shots"]))
        single_image_seconds = (
            max(0.0, queue_wait_seconds)
            + float(stages["setup"])
            + float(stages["reference_copy"])
            + float(stages["model_load"])
            + float(stages["identity_anchor_generation"])
            + max(shot_seconds, default=0.0)
            + float(stages["visual_qa"]) / panel_count
            + float(stages["contact_sheet"]) / panel_count
        )
        if len(result["shots"]) == 1:
            single_image_seconds = end_to_end_seconds
        result["performance"]["workflow_seconds"] = round(workflow_seconds, 3)
        result["performance"]["end_to_end_seconds"] = round(end_to_end_seconds, 3)
        result["performance"]["single_image_seconds"] = round(single_image_seconds, 3)
        result["performance"]["within_budget"] = (
            single_image_seconds <= job.visual_qa.latency_budget_seconds
        )
        result["performance"]["workflow_within_budget"] = (
            end_to_end_seconds <= job.visual_qa.latency_budget_seconds
        )

    try:
        reference_started = time.perf_counter()
        result["references"] = copy_reference_images(run_root, plan)
        stages["reference_copy"] = round(time.perf_counter() - reference_started, 3)
        write_json(run_root / "result.json", result)
        shots_by_id = {shot.shot_id: shot for shot in plan.shots}
        records_by_id = {record["shot_id"]: record for record in result["shots"]}
        anchor_records_by_id = {
            record["anchor_id"]: record for record in result["identity_anchors"]
        }
        anchor_paths_by_entity: dict[str, Path] = {}
        generated_outputs: dict[str, Path] = {}
        used_context_protocol = False
        if local_backend:
            load_started = time.perf_counter()
            if hasattr(active_backend, "load"):
                active_backend.load()
            else:
                active_backend = active_backend.__enter__()
                used_context_protocol = True
            stages["model_load"] = round(time.perf_counter() - load_started, 3)
            result["performance"]["backend_reused"] = False
        anchor_stage_started = time.perf_counter()
        try:
            for anchor in plan.identity_anchors:
                record = anchor_records_by_id[anchor.anchor_id]
                active_backend.settings = job.generation.model_copy(
                    update={"width": anchor.width, "height": anchor.height}
                )
                anchor_shot = PlannedShot(
                    shot_id=anchor.anchor_id,
                    prompt=anchor.prompt,
                    references=[anchor.source_reference],
                    seed=anchor.seed,
                )
                record["status"] = "running"
                anchor_error: Exception | None = None
                for attempt in range(1, job.generation.attempts + 1):
                    seed = anchor.seed + attempt - 1
                    started = time.perf_counter()
                    try:
                        image = active_backend.generate(anchor_shot, seed)
                        destination = run_root / f"identity-anchor-{anchor.anchor_id}.png"
                        try:
                            image.save(destination, format="PNG", optimize=True)
                        finally:
                            image.close()
                        destination.chmod(0o600)
                        record["attempts"].append(
                            {
                                "attempt": attempt,
                                "seed": seed,
                                "status": "succeeded",
                                "seconds": round(time.perf_counter() - started, 3),
                            }
                        )
                        record["status"] = "succeeded"
                        record["output"] = destination.name
                        anchor_paths_by_entity[anchor.entity_id] = destination
                        anchor_error = None
                        break
                    except Exception as error:
                        anchor_error = error
                        record["attempts"].append(
                            {
                                "attempt": attempt,
                                "seed": seed,
                                "status": "failed",
                                "seconds": round(time.perf_counter() - started, 3),
                                "error": f"{type(error).__name__}: {str(error)[:2000]}",
                            }
                        )
                        write_json(run_root / "result.json", result)
                if anchor_error is not None:
                    record["status"] = "failed"
                    raise RuntimeError(
                        f"identity anchor {anchor.anchor_id} failed after "
                        f"{job.generation.attempts} attempts"
                    ) from anchor_error
                write_json(run_root / "result.json", result)

            stages["identity_anchor_generation"] = round(
                time.perf_counter() - anchor_stage_started,
                3,
            )
            active_backend.settings = job.generation
            for shot_id in plan.execution_order:
                shot = shots_by_id[shot_id]
                effective_shot = apply_identity_anchor_paths(
                    shot,
                    anchor_paths_by_entity,
                )
                record = records_by_id[shot_id]
                continuity_path = None
                if shot.continuity_from:
                    parent_path = generated_outputs.get(shot.continuity_from)
                    if parent_path is None:
                        raise RuntimeError(
                            f"continuity source {shot.continuity_from} is not available "
                            f"for {shot.shot_id}"
                        )
                    continuity_path = prepare_continuity_reference(
                        run_root,
                        parent_path,
                        shot.shot_id,
                        shot.continuity_crop,
                    )
                    record["continuity"]["file"] = continuity_path.name
                record["status"] = "running"
                candidate_shot = effective_shot
                repair_index = 0
                destination = run_root / f"{shot.shot_id}.png"
                while True:
                    shot_error: Exception | None = None
                    for retry in range(job.generation.attempts):
                        attempt = len(record["attempts"]) + 1
                        seed = shot.seed + retry + repair_index * 1000
                        started = time.perf_counter()
                        try:
                            image = active_backend.generate(
                                candidate_shot,
                                seed,
                                continuity_path=continuity_path,
                            )
                            try:
                                image.save(destination, format="PNG", optimize=True)
                            finally:
                                image.close()
                            destination.chmod(0o600)
                            elapsed = time.perf_counter() - started
                            stages["panel_generation"] = round(
                                float(stages["panel_generation"]) + elapsed,
                                3,
                            )
                            if repair_index:
                                stages["selective_repair_generation"] = round(
                                    float(stages["selective_repair_generation"]) + elapsed,
                                    3,
                                )
                            record["attempts"].append(
                                {
                                    "attempt": attempt,
                                    "seed": seed,
                                    "kind": "repair" if repair_index else "initial",
                                    "status": "succeeded",
                                    "seconds": round(elapsed, 3),
                                }
                            )
                            shot_error = None
                            break
                        except Exception as error:
                            elapsed = time.perf_counter() - started
                            stages["panel_generation"] = round(
                                float(stages["panel_generation"]) + elapsed,
                                3,
                            )
                            shot_error = error
                            record["attempts"].append(
                                {
                                    "attempt": attempt,
                                    "seed": seed,
                                    "kind": "repair" if repair_index else "initial",
                                    "status": "failed",
                                    "seconds": round(elapsed, 3),
                                    "error": f"{type(error).__name__}: {str(error)[:2000]}",
                                }
                            )
                            write_json(run_root / "result.json", result)
                    if shot_error is not None:
                        record["status"] = "failed"
                        raise RuntimeError(
                            f"shot {shot.shot_id} failed after "
                            f"{job.generation.attempts} backend attempts"
                        ) from shot_error

                    if not job.visual_qa.enabled:
                        break
                    qa_started = time.perf_counter()
                    qa_result = qa_service.evaluate(
                        image_path=destination,
                        target_id=shot.shot_id,
                        evaluation_index=len(record["qa_history"]) + 1,
                        expected_size=(job.generation.width, job.generation.height),
                        references=candidate_shot.references,
                        settings=job.visual_qa,
                    )
                    qa_elapsed = time.perf_counter() - qa_started
                    stages["visual_qa"] = round(
                        float(stages["visual_qa"]) + qa_elapsed,
                        3,
                    )
                    record["qa_history"].append(qa_result.model_dump(mode="json"))
                    record["attempts"][-1]["qa_result_id"] = qa_result.qa_result_id
                    if qa_result.passed:
                        break
                    record["attempts"][-1]["status"] = "rejected_by_qa"
                    if repair_index >= job.visual_qa.max_auto_repairs:
                        record["status"] = "failed"
                        raise RuntimeError(
                            f"shot {shot.shot_id} failed visual QA: "
                            + ", ".join(qa_result.hard_failures)
                        )
                    rejected = run_root / (
                        f"qa-rejected-{shot.shot_id}-{repair_index + 1:02d}.png"
                    )
                    destination.replace(rejected)
                    rejected.chmod(0o600)
                    repair_index += 1
                    candidate_shot, repair_plan = qa_service.repair_plan(
                        shot=effective_shot,
                        result=qa_result,
                        repair_index=repair_index,
                    )
                    record["repairs"].append(
                        repair_plan.model_dump(mode="json")
                        | {"rejected_candidate": rejected.name}
                    )
                    write_json(run_root / "result.json", result)

                record["status"] = "succeeded"
                record["output"] = destination.name
                generated_outputs[shot.shot_id] = destination
                write_json(run_root / "result.json", result)
        finally:
            if local_backend:
                if used_context_protocol:
                    active_backend.__exit__(None, None, None)
                else:
                    active_backend.close()
        if plan.contact_sheet:
            contact_started = time.perf_counter()
            outputs_by_id = {
                record["shot_id"]: record["output"] for record in result["shots"]
            }
            result["contact_sheet"] = create_contact_sheet(
                run_root,
                [outputs_by_id[shot.shot_id] for shot in plan.shots],
                columns=plan.contact_sheet.columns,
                filename=plan.contact_sheet.filename,
            )
            stages["contact_sheet"] = round(time.perf_counter() - contact_started, 3)
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {str(error)[:2000]}"
        result["completed_at"] = utc_now().isoformat()
        finish_performance()
        write_json(run_root / "result.json", result)
        raise

    result["status"] = "succeeded"
    result["completed_at"] = utc_now().isoformat()
    finish_performance()
    write_json(run_root / "result.json", result)
    return run_root
