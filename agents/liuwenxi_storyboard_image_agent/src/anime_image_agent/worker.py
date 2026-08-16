from __future__ import annotations

import gc
import os
import time
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageDraw

from .artifacts import ArtifactStore
from .backend import (
    ModelLock,
    classify_generation_error,
    seed_and_prompt_digest,
)
from .config import MODEL_ID, PROFILE, Settings
from .contracts import QueueRecordV1, WaveTaskV1
from .io_utils import now
from .queue import QueueItemNotFoundError, QueueStore


class GeneratorBackend(Protocol):
    def generate(
        self,
        record: QueueRecordV1,
        task: WaveTaskV1,
        output: Path,
        worker_id: str,
        physical_gpu_ids: tuple[int, int],
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class FakeGenerator:
    def __init__(self, model_lock: ModelLock) -> None:
        self.model_lock = model_lock
        self.load_seconds = 0.0

    def generate(
        self,
        record: QueueRecordV1,
        task: WaveTaskV1,
        output: Path,
        worker_id: str,
        physical_gpu_ids: tuple[int, int],
    ) -> dict[str, Any]:
        started_at = now()
        started = time.perf_counter()
        seed, digest = seed_and_prompt_digest(record)
        red = 32 + seed % 160
        green = 32 + (seed >> 8) % 160
        blue = 32 + (seed >> 16) % 160
        image = Image.new("RGB", (PROFILE.width, PROFILE.height), (red, green, blue))
        draw = ImageDraw.Draw(image)
        stripe = max(8, PROFILE.width // 32)
        for x in range(0, PROFILE.width, stripe * 2):
            draw.rectangle(
                (x, 0, min(PROFILE.width - 1, x + stripe), PROFILE.height - 1),
                fill=((red + 40) % 256, (green + 80) % 256, (blue + 120) % 256),
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        completed_at = now()
        return {
            "model_id": MODEL_ID,
            "model_revision": self.model_lock.revision,
            "scheduler": "FakeScheduler",
            "seed": seed,
            "attempt": record.attempt,
            "gpu_ids": list(physical_gpu_ids),
            "worker_id": worker_id,
            "model_load_seconds": self.load_seconds,
            "generation_seconds": round(time.perf_counter() - started, 3),
            "peak_vram_gib": [0.0, 0.0],
            "positive_token_count": task.positive_token_count,
            "negative_token_count": task.negative_token_count,
            "prompt_sha256": digest,
            "started_at": started_at,
            "completed_at": completed_at,
        }

    def close(self) -> None:
        return


class QwenGenerator:
    def __init__(self, model_lock: ModelLock) -> None:
        import torch
        from diffusers import (
            AutoencoderKLQwenImage,
            FlowMatchEulerDiscreteScheduler,
            QwenImagePipeline,
            QwenImageTransformer2DModel,
        )

        if not torch.cuda.is_available() or torch.cuda.device_count() != 2:
            raise RuntimeError("each production worker must see exactly two CUDA devices")
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.set_float32_matmul_precision("high")
        for index in range(2):
            torch.cuda.empty_cache()

        load_started = time.perf_counter()
        transformer = QwenImageTransformer2DModel.from_pretrained(
            str(model_lock.snapshot),
            subfolder="transformer",
            torch_dtype=torch.bfloat16,
            use_safetensors=True,
            local_files_only=True,
            low_cpu_mem_usage=True,
            device_map="balanced",
            max_memory={0: PROFILE.max_memory_per_gpu, 1: PROFILE.max_memory_per_gpu, "cpu": "1GiB"},
        )
        device_map = getattr(transformer, "hf_device_map", None)
        if not device_map:
            raise RuntimeError("Accelerate did not create a transformer device map")
        devices = _normalized_devices(device_map)
        if devices != {0, 1}:
            raise RuntimeError(
                "transformer must be GPU-only and use both local devices; "
                f"got {sorted(map(str, devices))}"
            )
        vae = AutoencoderKLQwenImage.from_pretrained(
            str(model_lock.snapshot),
            subfolder="vae",
            torch_dtype=torch.bfloat16,
            use_safetensors=True,
            local_files_only=True,
            low_cpu_mem_usage=True,
        ).to("cuda:0")
        vae.enable_slicing()
        vae.enable_tiling()
        scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
            str(model_lock.snapshot),
            subfolder="scheduler",
            local_files_only=True,
        )
        self.pipeline = QwenImagePipeline(
            scheduler=scheduler,
            vae=vae,
            text_encoder=None,
            tokenizer=None,
            transformer=transformer,
        )
        self.pipeline.set_progress_bar_config(disable=True)
        self.execution_device = self.pipeline._execution_device
        if self.execution_device.type != "cuda":
            raise RuntimeError(f"pipeline execution device is not CUDA: {self.execution_device}")
        self.model_lock = model_lock
        self.transformer = transformer
        self.load_seconds = round(time.perf_counter() - load_started, 3)
        self.scheduler_name = scheduler.__class__.__name__

    def generate(
        self,
        record: QueueRecordV1,
        task: WaveTaskV1,
        output: Path,
        worker_id: str,
        physical_gpu_ids: tuple[int, int],
    ) -> dict[str, Any]:
        import torch

        for index in range(2):
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats(index)
        embeddings = torch.load(task.embedding_path, map_location="cpu", weights_only=True)
        dtype = self.transformer.dtype
        positive = _tensor_to_device(embeddings["positive"], self.execution_device, dtype)
        positive_mask = _tensor_to_device(embeddings["positive_mask"], self.execution_device)
        negative = _tensor_to_device(embeddings["negative"], self.execution_device, dtype)
        negative_mask = _tensor_to_device(embeddings["negative_mask"], self.execution_device)
        if negative_mask is None or bool(negative_mask.all()):
            raise RuntimeError("negative prompt mask must contain padding for True CFG")

        seed, digest = seed_and_prompt_digest(record)
        for index in range(2):
            torch.cuda.synchronize(index)
        started_at = now()
        started = time.perf_counter()
        with torch.inference_mode():
            image = self.pipeline(
                prompt=None,
                negative_prompt=None,
                prompt_embeds=positive,
                prompt_embeds_mask=positive_mask,
                negative_prompt_embeds=negative,
                negative_prompt_embeds_mask=negative_mask,
                width=PROFILE.width,
                height=PROFILE.height,
                num_inference_steps=PROFILE.steps,
                true_cfg_scale=PROFILE.true_cfg_scale,
                generator=torch.Generator(device=self.execution_device).manual_seed(seed),
                output_type="pil",
                max_sequence_length=PROFILE.max_sequence_length,
            ).images[0]
        for index in range(2):
            torch.cuda.synchronize(index)
        generation_seconds = round(time.perf_counter() - started, 3)
        completed_at = now()
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        peak = [round(torch.cuda.max_memory_allocated(index) / 1024**3, 3) for index in range(2)]
        del embeddings, positive, positive_mask, negative, negative_mask, image
        gc.collect()
        torch.cuda.empty_cache()
        return {
            "model_id": MODEL_ID,
            "model_revision": self.model_lock.revision,
            "scheduler": self.scheduler_name,
            "seed": seed,
            "attempt": record.attempt,
            "gpu_ids": list(physical_gpu_ids),
            "worker_id": worker_id,
            "model_load_seconds": self.load_seconds,
            "generation_seconds": generation_seconds,
            "peak_vram_gib": peak,
            "positive_token_count": task.positive_token_count,
            "negative_token_count": task.negative_token_count,
            "prompt_sha256": digest,
            "started_at": started_at,
            "completed_at": completed_at,
        }

    def close(self) -> None:
        import torch

        del self.pipeline, self.transformer
        gc.collect()
        torch.cuda.empty_cache()


def run_wave_worker(
    settings: Settings,
    wave_root: Path,
    worker_index: int,
    backend_name: str,
    model_lock: ModelLock,
) -> int:
    queue = QueueStore(settings)
    artifacts = ArtifactStore(settings)
    physical_gpu_ids = (worker_index * 2, worker_index * 2 + 1)
    worker_id = f"worker-{worker_index}-{os.getpid()}"
    generator: GeneratorBackend
    if backend_name == "fake":
        generator = FakeGenerator(model_lock)
    elif backend_name == "qwen":
        generator = QwenGenerator(model_lock)
    else:
        raise ValueError(f"unsupported backend: {backend_name}")
    queue.event(
        "worker_started",
        worker_id=worker_id,
        wave_id=wave_root.name,
        gpu_ids=list(physical_gpu_ids),
        backend=backend_name,
    )
    completed = 0
    try:
        while True:
            claimed = _claim_task(wave_root, worker_id)
            if claimed is None:
                break
            task_path, task = claimed
            try:
                record = queue.load_running(task.request_id)
                if record.attempt != task.attempt:
                    raise RuntimeError(
                        f"stale wave task attempt {task.attempt}; queue is {record.attempt}"
                    )
                output = wave_root / "outputs" / worker_id / f"{task.request_id}.png"
                metadata = generator.generate(
                    record,
                    task,
                    output,
                    worker_id,
                    physical_gpu_ids,
                )
                result = artifacts.commit_success(record, output, metadata)
                queue.complete(result)
                _finish_task(wave_root, task_path, "done")
                completed += 1
            except QueueItemNotFoundError:
                _finish_task(wave_root, task_path, "failed")
            except Exception as error:
                if backend_name == "qwen":
                    _release_cuda_cache()
                try:
                    record = queue.load_running(task.request_id)
                    committed = artifacts.load_committed_result(record)
                    if committed is not None:
                        queue.complete(committed)
                    else:
                        queue.retry_or_fail(
                            task.request_id,
                            classify_generation_error(error),
                        )
                except Exception as finalize_error:
                    queue.event(
                        "worker_finalize_deferred",
                        request_id=task.request_id,
                        worker_id=worker_id,
                        error_type=type(finalize_error).__name__,
                    )
                _finish_task(wave_root, task_path, "failed")
    finally:
        generator.close()
        queue.event(
            "worker_stopped",
            worker_id=worker_id,
            wave_id=wave_root.name,
            completed=completed,
        )
    return completed


def _claim_task(wave_root: Path, worker_id: str) -> tuple[Path, WaveTaskV1] | None:
    ready_root = wave_root / "tasks" / "ready"
    running_root = wave_root / "tasks" / "running"
    claim_root = wave_root / "tasks" / "claims"
    running_root.mkdir(parents=True, exist_ok=True)
    claim_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(ready_root.glob("*.json")):
        claim = claim_root / f"{source.stem}.lock"
        try:
            descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        try:
            os.write(descriptor, worker_id.encode("ascii"))
        finally:
            os.close(descriptor)
        destination = running_root / f"{worker_id}--{source.name}"
        try:
            os.replace(source, destination)
        except FileNotFoundError:
            continue
        task = _read_claimed_task(destination)
        return destination, task
    return None


def _read_claimed_task(path: Path) -> WaveTaskV1:
    last_error: OSError | None = None
    for _ in range(20):
        try:
            return WaveTaskV1.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as error:
            last_error = error
            time.sleep(0.01)
    assert last_error is not None
    raise last_error


def _finish_task(wave_root: Path, source: Path, state: str) -> None:
    destination_root = wave_root / "tasks" / state
    destination_root.mkdir(parents=True, exist_ok=True)
    if source.exists():
        os.replace(source, destination_root / source.name)


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


def _tensor_to_device(value: Any, device: Any, dtype: Any | None = None) -> Any:
    if value is None:
        return None
    if dtype is not None and value.is_floating_point():
        return value.to(device=device, dtype=dtype)
    return value.to(device=device)


def _release_cuda_cache() -> None:
    import torch

    gc.collect()
    torch.cuda.empty_cache()
