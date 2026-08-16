from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import (
    BASE_NEGATIVE_PROMPT,
    GPU_PAIRS,
    MODEL_ID,
    PROFILE,
    Settings,
)
from .contracts import (
    ImageErrorV1,
    QueueRecordV1,
    WaveTaskV1,
    prompt_sha256,
    seed_for_attempt,
)
from .io_utils import atomic_write_json, load_json, now


class PromptTooLongError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelLock:
    model_id: str
    revision: str
    snapshot: Path

    @classmethod
    def load(cls, path: Path) -> "ModelLock":
        payload = load_json(path)
        if payload.get("model_id") != MODEL_ID:
            raise RuntimeError(f"model lock contains unexpected model: {payload.get('model_id')}")
        snapshot = Path(str(payload["snapshot"]))
        if not snapshot.is_dir():
            raise FileNotFoundError(f"locked model snapshot is missing: {snapshot}")
        if any(snapshot.parents[1].rglob("*.incomplete")):
            raise RuntimeError("model cache contains incomplete files")
        return cls(model_id=MODEL_ID, revision=str(payload["revision"]), snapshot=snapshot)


@dataclass(frozen=True, slots=True)
class EncodeOutcome:
    tasks: list[WaveTaskV1]
    failures: list[tuple[QueueRecordV1, ImageErrorV1]]
    load_seconds: float
    encode_seconds: float
    peak_vram_gib: float


def effective_negative_prompt(record: QueueRecordV1) -> str:
    supplemental = record.job.prompt_spec.negative_prompt
    if not supplemental:
        return BASE_NEGATIVE_PROMPT
    return f"{BASE_NEGATIVE_PROMPT} {supplemental}"


def prepare_model(settings: Settings, *, max_workers: int = 4) -> ModelLock:
    if settings.model_lock.is_file():
        return ModelLock.load(settings.model_lock)

    from huggingface_hub import snapshot_download

    started = time.perf_counter()
    snapshot = Path(
        snapshot_download(
            repo_id=MODEL_ID,
            cache_dir=settings.hf_cache,
            max_workers=max_workers,
        )
    ).resolve()
    if any(snapshot.parents[1].rglob("*.incomplete")):
        raise RuntimeError("model download left incomplete files")
    revision = snapshot.name
    payload = {
        "schema_name": "ModelLockV1",
        "model_id": MODEL_ID,
        "revision": revision,
        "snapshot": str(snapshot),
        "download_seconds": round(time.perf_counter() - started, 3),
        "created_at": now().isoformat(),
    }
    atomic_write_json(settings.model_lock, payload)
    return ModelLock.load(settings.model_lock)


def validate_gpu_node(settings: Settings) -> list[dict[str, Any]]:
    import pynvml

    pynvml.nvmlInit()
    gpus: list[dict[str, Any]] = []
    try:
        count = pynvml.nvmlDeviceGetCount()
        if count != 8:
            raise RuntimeError(f"expected exactly 8 GPUs, found {count}")
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            raw_name = pynvml.nvmlDeviceGetName(handle)
            name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_mib = memory.total / 1024**2
            used_mib = memory.used / 1024**2
            if "A40" not in name.upper():
                raise RuntimeError(f"GPU {index} is {name}, expected NVIDIA A40")
            if total_mib < 45_000:
                raise RuntimeError(f"GPU {index} exposes only {total_mib:.0f} MiB")
            if used_mib > settings.gpu_idle_memory_mib:
                raise RuntimeError(
                    f"GPU {index} is using {used_mib:.0f} MiB; limit is "
                    f"{settings.gpu_idle_memory_mib} MiB"
                )
            gpus.append(
                {
                    "index": index,
                    "name": name,
                    "memory_total_mib": round(total_mib, 3),
                    "memory_used_mib": round(used_mib, 3),
                }
            )
    finally:
        pynvml.nvmlShutdown()
    return gpus


def wait_for_gpu_zero_release(settings: Settings, timeout_seconds: float = 30.0) -> None:
    import pynvml

    deadline = time.monotonic() + timeout_seconds
    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        while True:
            used_mib = pynvml.nvmlDeviceGetMemoryInfo(handle).used / 1024**2
            if used_mib <= settings.gpu_idle_memory_mib:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"prompt encoder did not release GPU 0: {used_mib:.0f} MiB remains"
                )
            time.sleep(1.0)
    finally:
        pynvml.nvmlShutdown()


class FakePromptEncoder:
    def encode(
        self,
        records: Iterable[QueueRecordV1],
        wave_id: str,
        embedding_root: Path,
    ) -> EncodeOutcome:
        started = time.perf_counter()
        tasks: list[WaveTaskV1] = []
        embedding_root.mkdir(parents=True, exist_ok=True)
        for record in records:
            path = embedding_root / f"{record.job.request_id}.json"
            atomic_write_json(path, {"fake": True, "request_id": record.job.request_id})
            tasks.append(
                WaveTaskV1(
                    wave_id=wave_id,
                    request_id=record.job.request_id,
                    attempt=record.attempt,
                    embedding_path=str(path),
                    positive_token_count=min(512, max(1, len(record.job.prompt_spec.positive_prompt))),
                    negative_token_count=min(512, max(1, len(effective_negative_prompt(record)))),
                )
            )
        elapsed = time.perf_counter() - started
        return EncodeOutcome(tasks, [], 0.0, elapsed, 0.0)


class QwenPromptEncoder:
    def __init__(self, model_lock: ModelLock) -> None:
        self.model_lock = model_lock

    def encode(
        self,
        records: Iterable[QueueRecordV1],
        wave_id: str,
        embedding_root: Path,
    ) -> EncodeOutcome:
        import torch
        from diffusers import QwenImagePipeline

        records = list(records)
        embedding_root.mkdir(parents=True, exist_ok=True)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(0)
        load_started = time.perf_counter()
        pipeline = QwenImagePipeline.from_pretrained(
            str(self.model_lock.snapshot),
            transformer=None,
            vae=None,
            scheduler=None,
            torch_dtype=torch.bfloat16,
            use_safetensors=True,
            local_files_only=True,
        )
        pipeline.text_encoder.to("cuda:0")
        device = torch.device("cuda:0")
        load_seconds = time.perf_counter() - load_started
        tasks: list[WaveTaskV1] = []
        failures: list[tuple[QueueRecordV1, ImageErrorV1]] = []
        encode_started = time.perf_counter()
        peak = 0.0
        try:
            for record in records:
                try:
                    positive, positive_mask = _encode_without_truncation(
                        pipeline,
                        record.job.prompt_spec.positive_prompt,
                        device,
                    )
                    negative, negative_mask = _encode_without_truncation(
                        pipeline,
                        effective_negative_prompt(record),
                        device,
                    )
                    positive_count = positive.shape[1]
                    negative_count = negative.shape[1]
                    positive, positive_mask = _pad_embeddings(
                        positive, positive_mask, PROFILE.max_sequence_length
                    )
                    negative, negative_mask = _pad_embeddings(
                        negative, negative_mask, PROFILE.max_sequence_length
                    )
                    embedding_path = embedding_root / f"{record.job.request_id}.pt"
                    torch.save(
                        {
                            "positive": positive.detach().cpu(),
                            "positive_mask": positive_mask.detach().cpu(),
                            "negative": negative.detach().cpu(),
                            "negative_mask": negative_mask.detach().cpu(),
                        },
                        embedding_path,
                    )
                    tasks.append(
                        WaveTaskV1(
                            wave_id=wave_id,
                            request_id=record.job.request_id,
                            attempt=record.attempt,
                            embedding_path=str(embedding_path),
                            positive_token_count=positive_count,
                            negative_token_count=negative_count,
                        )
                    )
                    del positive, positive_mask, negative, negative_mask
                except PromptTooLongError as error:
                    failures.append(
                        (
                            record,
                            ImageErrorV1(
                                code="PROMPT_TOO_LONG",
                                message=str(error),
                                retryable=False,
                            ),
                        )
                    )
                except Exception as error:
                    failures.append(
                        (
                            record,
                            ImageErrorV1(
                                code="PROMPT_ENCODING_FAILED",
                                message=f"{type(error).__name__}: {str(error)[:1800]}",
                                retryable=True,
                            ),
                        )
                    )
            torch.cuda.synchronize(0)
            peak = torch.cuda.max_memory_allocated(0) / 1024**3
        finally:
            del pipeline
            gc.collect()
            torch.cuda.empty_cache()
        return EncodeOutcome(
            tasks=tasks,
            failures=failures,
            load_seconds=round(load_seconds, 3),
            encode_seconds=round(time.perf_counter() - encode_started, 3),
            peak_vram_gib=round(peak, 3),
        )


def _encode_without_truncation(pipeline: Any, prompt: str, device: Any) -> tuple[Any, Any]:
    detection_limit = PROFILE.max_sequence_length + 1
    embeddings, mask = pipeline.encode_prompt(
        prompt,
        device=device,
        max_sequence_length=detection_limit,
    )
    token_count = embeddings.shape[1]
    if token_count > PROFILE.max_sequence_length:
        raise PromptTooLongError(
            f"prompt uses more than {PROFILE.max_sequence_length} encoded tokens"
        )
    return embeddings, mask


def _pad_embeddings(embeddings: Any, mask: Any, target_length: int) -> tuple[Any, Any]:
    import torch

    batch, sequence_length, hidden_size = embeddings.shape
    if sequence_length > target_length:
        raise PromptTooLongError(f"prompt uses {sequence_length} tokens; maximum is {target_length}")
    if mask is None:
        mask = torch.ones(
            (batch, sequence_length),
            device=embeddings.device,
            dtype=torch.long,
        )
    if sequence_length == target_length:
        return embeddings, mask
    padding_length = target_length - sequence_length
    return (
        torch.cat(
            (
                embeddings,
                torch.zeros(
                    (batch, padding_length, hidden_size),
                    device=embeddings.device,
                    dtype=embeddings.dtype,
                ),
            ),
            dim=1,
        ),
        torch.cat(
            (
                mask,
                torch.zeros(
                    (batch, padding_length),
                    device=mask.device,
                    dtype=mask.dtype,
                ),
            ),
            dim=1,
        ),
    )


def classify_generation_error(error: Exception) -> ImageErrorV1:
    from .artifacts import ImageValidationError

    message = f"{type(error).__name__}: {str(error)[:1800]}"
    lowered = message.lower()
    if isinstance(error, ImageValidationError):
        code = "MECHANICAL_QA_FAILED"
    elif "out of memory" in lowered or "cuda.*oom" in lowered:
        code = "CUDA_OOM"
    elif isinstance(error, FileNotFoundError):
        code = "EMBEDDING_MISSING"
    else:
        code = "GENERATION_FAILED"
    return ImageErrorV1(code=code, message=message, retryable=True)


def worker_pair(worker_index: int) -> tuple[int, int]:
    try:
        return GPU_PAIRS[worker_index]
    except IndexError as error:
        raise ValueError(f"worker index must be 0..{len(GPU_PAIRS) - 1}") from error


def seed_and_prompt_digest(record: QueueRecordV1) -> tuple[int, str]:
    return (
        seed_for_attempt(record.job.request_id, record.attempt),
        prompt_sha256(record.job, effective_negative_prompt(record)),
    )
