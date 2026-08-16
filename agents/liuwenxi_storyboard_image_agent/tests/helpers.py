from __future__ import annotations

import json
from pathlib import Path

from anime_image_agent.config import Settings
from anime_image_agent.contracts import ImageJobV1


ROOT = Path(__file__).resolve().parents[1]


def valid_job(request_id: str = "request-001", sequence_no: int = 1) -> ImageJobV1:
    payload = json.loads((ROOT / "examples" / "image_job.valid.json").read_text(encoding="utf-8"))
    payload["request_id"] = request_id
    payload["panel_id"] = f"panel-{sequence_no:03d}"
    payload["sequence_no"] = sequence_no
    payload["prompt_spec"]["prompt_id"] = f"prompt-{sequence_no:03d}"
    return ImageJobV1.model_validate(payload)


def make_settings(root: Path, *, wave_size: int = 32) -> Settings:
    return Settings(
        run_root=root / "run",
        output_root=root / "output",
        scratch_root=root / "scratch",
        model_root=root / "models",
        hf_cache=root / "hf-cache",
        gather_seconds=0.0,
        poll_seconds=0.01,
        wave_size=wave_size,
        max_attempts=3,
    )
