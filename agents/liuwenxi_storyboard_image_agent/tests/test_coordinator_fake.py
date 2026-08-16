from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from anime_image_agent.coordinator import Coordinator
from anime_image_agent.queue import QueueStore

from .helpers import make_settings, valid_job


def test_fake_backend_processes_32_jobs_with_four_workers(tmp_path) -> None:
    settings = make_settings(tmp_path, wave_size=32)
    queue = QueueStore(settings)
    for index in range(32):
        queue.enqueue(valid_job(f"request-{index:03d}", index))

    waves = Coordinator(settings, "fake").run(drain=True)
    assert waves == 1
    for index in range(32):
        status = queue.status(f"request-{index:03d}")
        assert status.state == "succeeded"
        assert status.result is not None
        generated = status.result.generated_image
        assert generated is not None
        assert generated.metadata.attempt == 1
        assert generated.metadata.gpu_ids in ([0, 1], [2, 3], [4, 5], [6, 7])
        image_path = Path(generated.artifact.uri)
        with Image.open(image_path) as image:
            assert image.size == (1664, 928)

    summaries = list((settings.run_root / "waves").glob("*/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["jobs"] == 32
    assert len(summary["worker_results"]) == 4
    assert all(worker["return_code"] == 0 for worker in summary["worker_results"])
    assert summary["states"] == {"succeeded": 32}
    assert not settings.wave_root.exists() or not any(settings.wave_root.iterdir())
