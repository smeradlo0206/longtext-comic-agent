from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


MODEL_ID = "Qwen/Qwen-Image-2512"
PLANNER_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
EDIT_MODEL_ID = "Qwen/Qwen-Image-Edit-2509"
RENDER_PROFILE = "qwen-image-2512-landscape-v1"
BASE_NEGATIVE_PROMPT = (
    "低分辨率，低画质，模糊，噪点，过曝，过饱和，构图混乱，透视错误，"
    "重复人物，多余肢体，肢体畸形，手指畸形，面部崩坏，现代建筑，现代服装，"
    "廉价特效，塑料质感，文字，字幕，书法，签名，标志，水印，边框。"
)


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    name: str = RENDER_PROFILE
    width: int = 1664
    height: int = 928
    steps: int = 50
    true_cfg_scale: float = 4.0
    max_sequence_length: int = 512
    max_memory_per_gpu: str = "24GiB"
    dtype: str = "bfloat16"


PROFILE = GenerationProfile()
GPU_PAIRS: tuple[tuple[int, int], ...] = ((0, 1), (2, 3), (4, 5), (6, 7))
RENDER_PROFILES: dict[str, tuple[int, int]] = {
    "landscape": (1664, 928),
    "portrait": (928, 1664),
    "square": (1328, 1328),
}


@dataclass(frozen=True, slots=True)
class Settings:
    run_root: Path
    output_root: Path
    scratch_root: Path
    model_root: Path
    hf_cache: Path
    gather_seconds: float = 2.0
    poll_seconds: float = 1.0
    wave_size: int = 32
    max_attempts: int = 3
    gpu_idle_memory_mib: int = 1024
    asset_root: Path = Path("assets/presets")
    scene_database: Path | None = None
    scene_wave_size: int = 8

    @classmethod
    def from_environment(cls) -> "Settings":
        persistent = Path(os.environ.get("RUN_ROOT", "/output/lwx/anime-agent/runs"))
        outputs = Path(os.environ.get("OUTPUT_ROOT", "/output/lwx/anime-agent/outputs"))
        scratch = Path(os.environ.get("SCRATCH_ROOT", "/tmp/lwx-anime-agent/scratch"))
        models = Path(os.environ.get("MODEL_ROOT", "/output/lwx/anime-agent/models"))
        hf_cache = Path(
            os.environ.get(
                "HF_HUB_CACHE",
                str(models / "huggingface" / "hub"),
            )
        )
        scene_run_root = persistent / "image-provider"
        return cls(
            run_root=scene_run_root,
            output_root=outputs / "image-provider",
            scratch_root=scratch / "image-provider",
            model_root=models / "qwen-image-2512",
            hf_cache=hf_cache,
            asset_root=Path(os.environ.get("ASSET_ROOT", "assets/presets")).resolve(),
            scene_database=Path(
                os.environ.get("SCENE_DATABASE", str(scene_run_root / "scene-jobs.sqlite3"))
            ),
        )

    @property
    def queue_root(self) -> Path:
        return self.run_root / "queue"

    @property
    def result_root(self) -> Path:
        return self.run_root / "results"

    @property
    def event_log(self) -> Path:
        return self.run_root / "events.jsonl"

    @property
    def model_lock(self) -> Path:
        return self.model_root / "model-lock.json"

    @property
    def planner_model_root(self) -> Path:
        return self.model_root.parent / "qwen2.5-vl-7b"

    @property
    def edit_model_root(self) -> Path:
        return self.model_root.parent / "qwen-image-edit-2509"

    @property
    def scene_db(self) -> Path:
        return self.scene_database or self.run_root / "scene-jobs.sqlite3"

    @property
    def coordinator_lock(self) -> Path:
        return self.run_root / "coordinator.lock"

    @property
    def scene_coordinator_lock(self) -> Path:
        return self.run_root / "scene-coordinator.lock"

    @property
    def wave_root(self) -> Path:
        return self.scratch_root / "waves"

    def ensure_directories(self) -> None:
        for path in (
            self.run_root,
            self.output_root,
            self.scratch_root,
            self.model_root,
            self.result_root,
            self.wave_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_root": str(self.run_root),
            "output_root": str(self.output_root),
            "scratch_root": str(self.scratch_root),
            "model_root": str(self.model_root),
            "hf_cache": str(self.hf_cache),
            "gather_seconds": self.gather_seconds,
            "poll_seconds": self.poll_seconds,
            "wave_size": self.wave_size,
            "max_attempts": self.max_attempts,
            "gpu_idle_memory_mib": self.gpu_idle_memory_mib,
            "asset_root": str(self.asset_root),
            "scene_database": str(self.scene_db),
            "scene_wave_size": self.scene_wave_size,
        }

    @classmethod
    def from_file(cls, path: Path) -> "Settings":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            run_root=Path(payload["run_root"]),
            output_root=Path(payload["output_root"]),
            scratch_root=Path(payload["scratch_root"]),
            model_root=Path(payload["model_root"]),
            hf_cache=Path(payload["hf_cache"]),
            gather_seconds=float(payload["gather_seconds"]),
            poll_seconds=float(payload["poll_seconds"]),
            wave_size=int(payload["wave_size"]),
            max_attempts=int(payload["max_attempts"]),
            gpu_idle_memory_mib=int(payload["gpu_idle_memory_mib"]),
            asset_root=Path(payload.get("asset_root", "assets/presets")),
            scene_database=Path(payload.get("scene_database", Path(payload["run_root"]) / "scene-jobs.sqlite3")),
            scene_wave_size=int(payload.get("scene_wave_size", 8)),
        )
