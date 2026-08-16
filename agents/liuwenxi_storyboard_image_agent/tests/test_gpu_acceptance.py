from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from anime_image_agent.backend import validate_gpu_node
from anime_image_agent.config import Settings
from anime_image_agent.coordinator import Coordinator
from anime_image_agent.queue import QueueStore

from .helpers import valid_job


pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("RUN_GPU_ACCEPTANCE") != "1",
        reason="set RUN_GPU_ACCEPTANCE=1 on the exclusive A40 node",
    ),
]


def isolated_gpu_settings(name: str) -> Settings:
    base = Settings.from_environment()
    run_id = f"{name}-{uuid.uuid4().hex[:8]}"
    return Settings(
        run_root=base.run_root / "gpu-acceptance" / run_id,
        output_root=base.output_root / "gpu-acceptance" / run_id,
        scratch_root=base.scratch_root / "gpu-acceptance" / run_id,
        model_root=base.model_root,
        hf_cache=base.hf_cache,
        gather_seconds=0.0,
        poll_seconds=0.1,
        wave_size=32,
        max_attempts=3,
        gpu_idle_memory_mib=base.gpu_idle_memory_mib,
    )


def test_gpu_smoke_single_panel() -> None:
    settings = isolated_gpu_settings("smoke")
    gpus = validate_gpu_node(settings)
    assert len(gpus) == 8
    queue = QueueStore(settings)
    queue.enqueue(valid_job("gpu-smoke-panel", 1))
    assert Coordinator(settings, "qwen").run(drain=True) == 1
    result = queue.status("gpu-smoke-panel").result
    assert result is not None and result.generated_image is not None
    assert Path(result.generated_image.artifact.uri).is_file()


def test_four_panels_use_all_eight_gpus_concurrently() -> None:
    settings = isolated_gpu_settings("parallel")
    queue = QueueStore(settings)
    for index in range(4):
        queue.enqueue(valid_job(f"gpu-parallel-{index}", index))
    assert Coordinator(settings, "qwen").run(drain=True) == 1

    gpu_pairs = set()
    intervals = []
    for index in range(4):
        result = queue.status(f"gpu-parallel-{index}").result
        assert result is not None and result.generated_image is not None
        metadata = result.generated_image.metadata
        gpu_pairs.add(tuple(metadata.gpu_ids))
        intervals.append((metadata.started_at, metadata.completed_at))
    assert gpu_pairs == {(0, 1), (2, 3), (4, 5), (6, 7)}
    assert max(start for start, _ in intervals) < min(end for _, end in intervals)

    summary_path = next((settings.run_root / "waves").glob("*/summary.json"))
    import json

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(summary["worker_results"]) == 4
    assert all(worker["return_code"] == 0 for worker in summary["worker_results"])
    for index in range(8):
        peak = summary["telemetry"]["per_gpu"][str(index)]
        assert peak["peak_memory_mib"] > 18_000
        assert peak["peak_gpu_utilization"] > 0


def test_twelve_panel_wave_loads_four_workers_once_and_is_idempotent() -> None:
    settings = isolated_gpu_settings("long-batch")
    queue = QueueStore(settings)
    for index in range(12):
        queue.enqueue(valid_job(f"gpu-long-{index:02d}", index))
    coordinator = Coordinator(settings, "qwen")
    assert coordinator.run(drain=True) == 1

    hashes = {}
    worker_ids = set()
    for index in range(12):
        request_id = f"gpu-long-{index:02d}"
        result = queue.status(request_id).result
        assert result is not None and result.generated_image is not None
        hashes[request_id] = result.generated_image.artifact.sha256
        worker_ids.add(result.generated_image.metadata.worker_id)
    assert len(worker_ids) == 4

    assert Coordinator(settings, "qwen").run(drain=True) == 0
    for request_id, expected_hash in hashes.items():
        result = queue.status(request_id).result
        assert result is not None and result.generated_image is not None
        assert result.generated_image.artifact.sha256 == expected_hash
