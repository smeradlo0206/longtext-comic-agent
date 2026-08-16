from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from anime_image_agent.config import EDIT_MODEL_ID, Settings
from anime_image_agent.scene_contracts import SceneJobStatus
from anime_image_agent.scene_coordinator import SceneCoordinator
from anime_image_agent.scene_store import SceneStore


pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("RUN_SCENE_GPU_ACCEPTANCE") != "1",
        reason="set RUN_SCENE_GPU_ACCEPTANCE=1 after installing demo-v1 reference assets",
    ),
]


def test_qwen_image_edit_three_profiles_and_lineage() -> None:
    root = Path(__file__).resolve().parents[1]
    job = __import__("anime_image_agent.scene_contracts", fromlist=["SceneJobV1"]).SceneJobV1.model_validate(
        {
            **__import__("json").loads((root / "examples" / "scene_job.valid.json").read_text(encoding="utf-8")),
            "request_id": f"gpu-scene-{uuid.uuid4().hex[:8]}",
            "panels": [
                {
                    **__import__("json").loads(
                        (root / "examples" / "scene_job.valid.json").read_text(encoding="utf-8")
                    )["panels"][0],
                    "panel_id": f"panel-{index}",
                    "sequence_no": index,
                    "render_profile": profile,
                }
                for index, profile in enumerate(("landscape", "portrait", "square"))
            ],
        }
    )
    base = Settings.from_environment()
    run_id = job.request_id
    settings = Settings(
        run_root=base.run_root / "scene-gpu-acceptance" / run_id,
        output_root=base.output_root / "scene-gpu-acceptance" / run_id,
        scratch_root=base.scratch_root / "scene-gpu-acceptance" / run_id,
        model_root=base.model_root,
        hf_cache=base.hf_cache,
        poll_seconds=0.1,
        max_attempts=3,
        asset_root=base.asset_root,
        scene_database=base.run_root / "scene-gpu-acceptance" / run_id / "scene.sqlite3",
    )
    store = SceneStore(settings.scene_db)
    store.submit(job)
    assert SceneCoordinator(settings, backend="qwen", store=store).run(drain=True) == 1
    result = store.result(job.request_id)
    assert result.status == SceneJobStatus.SUCCEEDED
    assert [(item.artifact.width, item.artifact.height) for item in result.panels] == [
        (1664, 928),
        (928, 1664),
        (1328, 1328),
    ]
    for panel in result.panels:
        assert panel.metadata.model_id == EDIT_MODEL_ID
        assert panel.metadata.seed == panel.generation_spec.seed
        assert len(panel.metadata.gpu_ids) == 2
        assert Path(panel.artifact.uri).is_file()
