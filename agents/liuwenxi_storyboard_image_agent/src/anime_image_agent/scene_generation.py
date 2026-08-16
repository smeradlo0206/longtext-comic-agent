from __future__ import annotations

import gc
import hashlib
import json
import math
import multiprocessing as mp
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageDraw, ImageStat
from pydantic import BaseModel, ConfigDict, Field

from .config import EDIT_MODEL_ID, GPU_PAIRS, Settings
from .io_utils import atomic_write_json, now, sha256_file
from .scene_contracts import (
    GenerationSpecV1,
    PanelArtifactV1,
    PanelGenerationMetadataV1,
    SceneErrorV1,
)
from .telemetry import monitor, summarize


os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


class GenerationFailure(RuntimeError):
    def __init__(self, error: SceneErrorV1) -> None:
        super().__init__(error.message)
        self.error = error


class ScenePromptTooLongError(ValueError):
    pass


class SceneGenerator(Protocol):
    def condition_wave(
        self,
        specs: list[GenerationSpecV1],
    ) -> tuple[list["ConditionTask"], dict[str, SceneErrorV1]]: ...

    def generate_conditioned_wave(
        self,
        tasks: list["ConditionTask"],
        output_roots: dict[str, Path],
        attempts: dict[str, int],
    ) -> dict[str, tuple[PanelArtifactV1, PanelGenerationMetadataV1] | SceneErrorV1]: ...


class EditModelLock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model_id: str
    revision: str
    snapshot: str


class ConditionTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    spec: GenerationSpecV1
    embedding_path: str
    positive_token_count: int = Field(gt=0, le=1024)
    negative_token_count: int = Field(gt=0, le=1024)


def prepare_locked_model(model_id: str, root: Path, cache: Path) -> EditModelLock:
    lock_path = root / "model-lock.json"
    if lock_path.is_file():
        lock = EditModelLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
        if lock.model_id != model_id or not Path(lock.snapshot).is_dir():
            raise RuntimeError(f"invalid model lock: {lock_path}")
        return lock
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(repo_id=model_id, cache_dir=cache, max_workers=4)).resolve()
    lock = EditModelLock(model_id=model_id, revision=snapshot.name, snapshot=str(snapshot))
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(lock_path, lock)
    return lock


class FakeSceneGenerator:
    def __init__(self, fail_panel_ids: set[str] | None = None) -> None:
        self.fail_panel_ids = fail_panel_ids or set()

    def condition_wave(
        self,
        specs: list[GenerationSpecV1],
    ) -> tuple[list[ConditionTask], dict[str, SceneErrorV1]]:
        tasks = [
            ConditionTask(
                spec=spec,
                embedding_path="fake://conditioned",
                positive_token_count=min(1024, max(1, len(spec.positive_prompt))),
                negative_token_count=min(1024, max(1, len(spec.negative_prompt))),
            )
            for spec in specs
        ]
        return tasks, {}

    def generate_conditioned_wave(
        self,
        tasks: list[ConditionTask],
        output_roots: dict[str, Path],
        attempts: dict[str, int],
    ) -> dict[str, tuple[PanelArtifactV1, PanelGenerationMetadataV1] | SceneErrorV1]:
        results = {}
        for index, task in enumerate(tasks):
            spec = task.spec
            key = generation_key(spec)
            if spec.panel_id in self.fail_panel_ids:
                results[key] = SceneErrorV1(
                    code="INJECTED_FAILURE", message="fake generation failure", retryable=False
                )
                continue
            started = time.perf_counter()
            root = output_roots[key]
            image_path = root / "image.png"
            root.mkdir(parents=True, exist_ok=True)
            colors = (
                32 + spec.seed % 160,
                32 + (spec.seed >> 8) % 160,
                32 + (spec.seed >> 16) % 160,
            )
            image = Image.new("RGB", (spec.width, spec.height), colors)
            draw = ImageDraw.Draw(image)
            for x in range(0, spec.width, max(16, spec.width // 16) * 2):
                draw.rectangle((x, 0, min(spec.width - 1, x + 24), spec.height - 1), fill=colors[::-1])
            _atomic_save_png(image, image_path)
            artifact = inspect_scene_image(image_path, spec)
            metadata = PanelGenerationMetadataV1(
                model_id=EDIT_MODEL_ID,
                model_revision="fake-test",
                seed=spec.seed,
                attempt=attempts[key],
                worker_id=f"fake-worker-{index % 4}",
                gpu_ids=list(GPU_PAIRS[index % 4]),
                generation_seconds=round(time.perf_counter() - started, 3),
                completed_at=now(),
            )
            atomic_write_json(root / "generation-spec.json", spec)
            atomic_write_json(root / "metadata.json", metadata)
            results[key] = (artifact, metadata)
        return results


class QwenImageEdit2509Adapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = prepare_locked_model(EDIT_MODEL_ID, settings.edit_model_root, settings.hf_cache)

    def condition_wave(
        self,
        specs: list[GenerationSpecV1],
    ) -> tuple[list[ConditionTask], dict[str, SceneErrorV1]]:
        condition_root = self.settings.scratch_root / "scene-conditioning" / f"wave-{int(time.time() * 1000)}"
        condition_root.mkdir(parents=True, exist_ok=True)
        return self._condition(specs, condition_root)

    def generate_conditioned_wave(
        self,
        tasks: list[ConditionTask],
        output_roots: dict[str, Path],
        attempts: dict[str, int],
    ) -> dict[str, tuple[PanelArtifactV1, PanelGenerationMetadataV1] | SceneErrorV1]:
        worker_count = min(4, len(tasks))
        wave_root = Path(tasks[0].embedding_path).parent if tasks else self.settings.scratch_root
        telemetry_path = wave_root / "gpu-telemetry.jsonl"
        stop_file = wave_root / "telemetry.stop"
        monitor_context = mp.get_context("spawn")
        monitor_process = monitor_context.Process(
            target=monitor,
            args=(telemetry_path, stop_file, 1.0),
        )
        monitor_process.start()
        partitions = [tasks[index::worker_count] for index in range(worker_count)] if worker_count else []
        context = mp.get_context("spawn")
        processes: list[mp.Process] = []
        result_paths: list[Path] = []
        try:
            for worker_index, partition in enumerate(partitions):
                result_path = wave_root / f"worker-{worker_index}.json"
                result_path.unlink(missing_ok=True)
                process = context.Process(
                    target=_edit_worker_entry,
                    args=(
                        self.lock.model_dump(mode="json"),
                        [task.model_dump(mode="json") for task in partition],
                        {key: str(value) for key, value in output_roots.items()},
                        attempts,
                        worker_index,
                        str(result_path),
                    ),
                )
                process.start()
                processes.append(process)
                result_paths.append(result_path)
            for process in processes:
                process.join()
        finally:
            stop_file.touch()
            monitor_process.join(timeout=10)
            if monitor_process.is_alive():
                monitor_process.terminate()
                monitor_process.join(timeout=5)
        results: dict[str, tuple[PanelArtifactV1, PanelGenerationMetadataV1] | SceneErrorV1] = {}
        for partition, process, path in zip(partitions, processes, result_paths, strict=True):
            if not path.is_file():
                for task in partition:
                    results[generation_key(task.spec)] = SceneErrorV1(
                        code="WORKER_CRASH",
                        message=f"Image Edit worker exited with code {process.exitcode}",
                        retryable=True,
                    )
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for task_key, item in payload.items():
                if "error" in item:
                    results[task_key] = SceneErrorV1.model_validate(item["error"])
                else:
                    results[task_key] = (
                        PanelArtifactV1.model_validate(item["artifact"]),
                        PanelGenerationMetadataV1.model_validate(item["metadata"]),
                    )
        atomic_write_json(
            wave_root / "generation-summary.json",
            {
                "tasks": len(tasks),
                "workers": worker_count,
                "telemetry": summarize(telemetry_path),
                "completed_at": now().isoformat(),
            },
        )
        return results

    def _condition(
        self,
        specs: list[GenerationSpecV1],
        root: Path,
    ) -> tuple[list[ConditionTask], dict[str, SceneErrorV1]]:
        tasks: list[ConditionTask] = []
        failures: dict[str, SceneErrorV1] = {}
        worker_count = min(8, len(specs))
        partitions = [specs[index::worker_count] for index in range(worker_count)] if worker_count else []
        context = mp.get_context("spawn")
        processes: list[mp.Process] = []
        result_paths: list[Path] = []
        for gpu_index, partition in enumerate(partitions):
            result_path = root / f"condition-{gpu_index}.json"
            process = context.Process(
                target=_condition_worker_entry,
                args=(
                    self.lock.model_dump(mode="json"),
                    [spec.model_dump(mode="json") for spec in partition],
                    gpu_index,
                    str(root),
                    str(result_path),
                ),
            )
            process.start()
            processes.append(process)
            result_paths.append(result_path)
        for process in processes:
            process.join()
        for partition, process, path in zip(partitions, processes, result_paths, strict=True):
            if not path.is_file():
                for spec in partition:
                    failures[generation_key(spec)] = SceneErrorV1(
                        code="CONDITIONING_WORKER_CRASH",
                        message=f"conditioning worker exited with code {process.exitcode}",
                        retryable=True,
                    )
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for spec in partition:
                key = generation_key(spec)
                item = payload.get(key)
                if item is None:
                    failures[key] = SceneErrorV1(
                        code="CONDITIONING_RESULT_MISSING",
                        message="conditioning worker omitted task result",
                        retryable=True,
                    )
                    continue
                if "error" in item:
                    failures[key] = SceneErrorV1.model_validate(item["error"])
                else:
                    tasks.append(ConditionTask.model_validate(item["task"]))
        return tasks, failures


def _condition_worker_entry(
    lock_payload: dict[str, Any],
    spec_payloads: list[dict[str, Any]],
    gpu_index: int,
    root: str,
    result_path: str,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    import torch
    from diffusers import QwenImageEditPlusPipeline

    lock = EditModelLock.model_validate(lock_payload)
    specs = [GenerationSpecV1.model_validate(item) for item in spec_payloads]
    results: dict[str, dict[str, Any]] = {}
    pipeline = None
    try:
        pipeline = QwenImageEditPlusPipeline.from_pretrained(
            lock.snapshot,
            transformer=None,
            vae=None,
            scheduler=None,
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        )
        pipeline.text_encoder.requires_grad_(False).eval().to("cuda:0")
        for spec in specs:
            try:
                images = [Image.open(reference.uri).convert("RGB") for reference in spec.references]
                condition_images = _prepare_qwen_edit_condition_images(pipeline, images)
                positive, positive_mask, positive_count = _encode_prompt_to_cpu(
                    pipeline,
                    prompt=spec.positive_prompt,
                    images=condition_images,
                    device=torch.device("cuda:0"),
                    max_sequence_length=spec.max_sequence_length,
                )
                torch.cuda.empty_cache()

                negative, negative_mask, negative_count = _encode_prompt_to_cpu(
                    pipeline,
                    prompt=spec.negative_prompt,
                    images=condition_images,
                    device=torch.device("cuda:0"),
                    max_sequence_length=spec.max_sequence_length,
                )
                torch.cuda.empty_cache()
                task_digest = hashlib.sha256(generation_key(spec).encode("utf-8")).hexdigest()
                path = Path(root) / f"{task_digest}.pt"
                torch.save(
                    {
                        "positive": positive,
                        "positive_mask": positive_mask,
                        "negative": negative,
                        "negative_mask": negative_mask,
                    },
                    path,
                )
                task = ConditionTask(
                    spec=spec,
                    embedding_path=str(path),
                    positive_token_count=positive_count,
                    negative_token_count=negative_count,
                )
                results[generation_key(spec)] = {"task": task.model_dump(mode="json")}
            except Exception as error:
                results[generation_key(spec)] = {
                    "error": classify_scene_generation_error(error, "CONDITIONING_FAILED").model_dump(mode="json")
                }
    finally:
        if pipeline is not None:
            del pipeline
        gc.collect()
        torch.cuda.empty_cache()
        atomic_write_json(Path(result_path), results)


def _prepare_qwen_edit_condition_images(
    pipeline: Any,
    images: list[Image.Image],
) -> list[Image.Image]:
    target_area = 384 * 384
    prepared = []
    for image in images:
        ratio = image.width / image.height
        raw_width = math.sqrt(target_area * ratio)
        raw_height = raw_width / ratio
        width = round(raw_width / 32) * 32
        height = round(raw_height / 32) * 32
        prepared.append(pipeline.image_processor.resize(image, height, width))
    return prepared


def _encode_prompt_to_cpu(
    pipeline: Any,
    *,
    prompt: str,
    images: list[Image.Image],
    device: Any,
    max_sequence_length: int,
) -> tuple[Any, Any | None, int]:
    import torch

    token_count = _text_token_count(pipeline, prompt)
    if token_count > max_sequence_length:
        raise ScenePromptTooLongError(
            f"prompt uses {token_count} text tokens; maximum is {max_sequence_length}"
        )
    with torch.inference_mode():
        embeddings, mask = pipeline.encode_prompt(
            prompt=prompt,
            image=images,
            device=device,
            max_sequence_length=max_sequence_length,
        )
    if mask is None:
        mask = torch.ones(
            embeddings.shape[:2],
            dtype=torch.long,
            device=embeddings.device,
        )
    return (
        embeddings.detach().cpu(),
        mask.detach().cpu(),
        token_count,
    )


def _text_token_count(pipeline: Any, prompt: str) -> int:
    tokenizer = getattr(pipeline, "tokenizer", None)
    if tokenizer is None:
        processor = getattr(pipeline, "processor", None)
        tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None:
        raise RuntimeError("Image Edit pipeline does not expose a tokenizer")
    input_ids = tokenizer(
        prompt,
        add_special_tokens=False,
        truncation=False,
        return_attention_mask=False,
    )["input_ids"]
    if input_ids and isinstance(input_ids[0], list):
        input_ids = input_ids[0]
    return len(input_ids)


def _edit_worker_entry(
    lock_payload: dict[str, Any],
    task_payloads: list[dict[str, Any]],
    output_roots: dict[str, str],
    attempts: dict[str, int],
    worker_index: int,
    result_path: str,
) -> None:
    physical_pair = GPU_PAIRS[worker_index]
    os.environ["CUDA_VISIBLE_DEVICES"] = f"{physical_pair[0]},{physical_pair[1]}"
    lock = EditModelLock.model_validate(lock_payload)
    tasks = [ConditionTask.model_validate(item) for item in task_payloads]
    results: dict[str, dict[str, Any]] = {}
    generator = None
    try:
        generator = _QwenEditWorker(lock, worker_index, physical_pair)
        for task in tasks:
            key = generation_key(task.spec)
            try:
                artifact, metadata = generator.generate(
                    task,
                    Path(output_roots[key]),
                    attempts[key],
                )
                results[key] = {
                    "artifact": artifact.model_dump(mode="json"),
                    "metadata": metadata.model_dump(mode="json"),
                }
            except Exception as error:
                results[key] = {
                    "error": classify_scene_generation_error(error, "GENERATION_FAILED").model_dump(mode="json")
                }
    finally:
        if generator is not None:
            generator.close()
        atomic_write_json(Path(result_path), results)


class _QwenEditWorker:
    def __init__(self, lock: EditModelLock, worker_index: int, physical_pair: tuple[int, int]) -> None:
        import torch
        from diffusers import (
            AutoencoderKLQwenImage,
            FlowMatchEulerDiscreteScheduler,
            QwenImageEditPlusPipeline,
            QwenImageTransformer2DModel,
        )

        if torch.cuda.device_count() != 2:
            raise RuntimeError("Image Edit worker must see exactly two CUDA devices")
        transformer = QwenImageTransformer2DModel.from_pretrained(
            lock.snapshot,
            subfolder="transformer",
            torch_dtype=torch.bfloat16,
            local_files_only=True,
            low_cpu_mem_usage=True,
            device_map="balanced",
            max_memory={0: "44GiB", 1: "44GiB", "cpu": "1GiB"},
        )
        device_map = getattr(transformer, "hf_device_map", None)
        if not device_map or _normalized_devices(device_map) != {0, 1}:
            raise RuntimeError(f"Image Edit transformer must use both GPUs, got {device_map}")
        vae = AutoencoderKLQwenImage.from_pretrained(
            lock.snapshot,
            subfolder="vae",
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        ).to("cuda:0")
        vae.enable_slicing()
        vae.enable_tiling()
        scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
            lock.snapshot, subfolder="scheduler", local_files_only=True
        )
        self.pipeline = QwenImageEditPlusPipeline(
            scheduler=scheduler,
            vae=vae,
            text_encoder=None,
            tokenizer=None,
            processor=None,
            transformer=transformer,
        )
        self.pipeline.set_progress_bar_config(disable=True)
        self.lock = lock
        self.worker_id = f"edit-worker-{worker_index}"
        self.physical_pair = physical_pair

    def generate(
        self, task: ConditionTask, output_root: Path, attempt: int
    ) -> tuple[PanelArtifactV1, PanelGenerationMetadataV1]:
        import torch

        spec = task.spec
        started = time.perf_counter()
        embeddings = torch.load(task.embedding_path, map_location="cpu", weights_only=True)
        device = self.pipeline._execution_device
        dtype = self.pipeline.transformer.dtype
        images = [Image.open(reference.uri).convert("RGB") for reference in spec.references]
        torch_generator = torch.Generator(device=device).manual_seed(spec.seed)
        result = self.pipeline(
            image=images,
            prompt_embeds=embeddings["positive"].to(device=device, dtype=dtype),
            prompt_embeds_mask=_to_device(embeddings["positive_mask"], device),
            negative_prompt_embeds=embeddings["negative"].to(device=device, dtype=dtype),
            negative_prompt_embeds_mask=_to_device(embeddings["negative_mask"], device),
            true_cfg_scale=spec.true_cfg_scale,
            guidance_scale=spec.guidance_scale,
            height=spec.height,
            width=spec.width,
            num_inference_steps=spec.steps,
            generator=torch_generator,
            max_sequence_length=spec.max_sequence_length,
        )
        output_root.mkdir(parents=True, exist_ok=True)
        image_path = output_root / "image.png"
        _atomic_save_png(result.images[0], image_path)
        artifact = inspect_scene_image(image_path, spec)
        metadata = PanelGenerationMetadataV1(
            model_id=EDIT_MODEL_ID,
            model_revision=self.lock.revision,
            seed=spec.seed,
            attempt=attempt,
            worker_id=self.worker_id,
            gpu_ids=list(self.physical_pair),
            generation_seconds=round(time.perf_counter() - started, 3),
            completed_at=now(),
        )
        atomic_write_json(output_root / "generation-spec.json", spec)
        atomic_write_json(output_root / "metadata.json", metadata)
        return artifact, metadata

    def close(self) -> None:
        del self.pipeline
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except RuntimeError:
            pass


def inspect_scene_image(path: Path, spec: GenerationSpecV1) -> PanelArtifactV1:
    with Image.open(path) as opened:
        opened.load()
        if opened.format != "PNG":
            raise ValueError("generated artifact must be PNG")
        if opened.size != (spec.width, spec.height):
            raise ValueError(f"expected {spec.width}x{spec.height}, got {opened.size}")
        variance = sum(float(value) for value in ImageStat.Stat(opened.convert("RGB")).var)
        if variance <= 0:
            raise ValueError("generated artifact is blank")
    return PanelArtifactV1(
        image_id=_image_id(spec.request_id, spec.panel_id),
        uri=str(path.resolve()),
        url=f"/v1/artifacts/{_image_id(spec.request_id, spec.panel_id)}",
        sha256=sha256_file(path),
        width=spec.width,
        height=spec.height,
    )


def classify_scene_generation_error(error: Exception, default_code: str) -> SceneErrorV1:
    message = f"{type(error).__name__}: {str(error)[:1800]}"
    lowered = message.lower()
    retryable = True
    if isinstance(error, ScenePromptTooLongError):
        code = "PROMPT_TOO_LONG"
        retryable = False
    elif "out of memory" in lowered:
        code = "CUDA_OOM"
    elif isinstance(error, FileNotFoundError):
        code = "REFERENCE_MISSING"
    else:
        code = default_code
    return SceneErrorV1(code=code, message=message, retryable=retryable)


def _mask_count(mask: Any, fallback: int) -> int:
    if mask is None:
        return fallback
    return int(mask[0].sum().item())


def _to_device(value: Any, device: Any) -> Any:
    return None if value is None else value.to(device=device)


def _image_id(request_id: str, panel_id: str) -> str:
    candidate = f"{request_id}.{panel_id}.g1"
    if len(candidate) <= 128:
        return candidate
    return "img-" + hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:24]


def generation_key(spec: GenerationSpecV1) -> str:
    return f"{spec.request_id}:{spec.panel_id}"


def _atomic_save_png(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        image.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _normalized_devices(device_map: dict[str, Any]) -> set[int | str]:
    import torch

    devices: set[int | str] = set()
    for device in device_map.values():
        if isinstance(device, torch.device):
            device = device.index if device.type == "cuda" else device.type
        if isinstance(device, str) and device.startswith("cuda:"):
            device = int(device.split(":", 1)[1])
        devices.add(device)
    return devices
