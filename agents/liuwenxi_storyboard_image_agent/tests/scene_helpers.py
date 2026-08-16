from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from anime_image_agent.assets import PresetAssetRepository
from anime_image_agent.config import Settings
from anime_image_agent.scene_contracts import SceneJobV1
from anime_image_agent.upstream_contracts import UpstreamSceneEnvelopeV1


def make_scene_settings(root: Path) -> Settings:
    return Settings(
        run_root=root / "run",
        output_root=root / "output",
        scratch_root=root / "scratch",
        model_root=root / "models" / "qwen-image-2512",
        hf_cache=root / "hf-cache",
        gather_seconds=0,
        poll_seconds=0.01,
        wave_size=32,
        max_attempts=3,
        asset_root=root / "assets" / "presets",
        scene_database=root / "run" / "scene.sqlite3",
    )


def make_asset_repository(settings: Settings, two_characters: bool = False) -> PresetAssetRepository:
    profile = settings.asset_root / "demo-v1"
    assets = []
    characters = []
    source_specs = [
        ("characters/char-a.png", "char-a-ref", "identity_reference", "char-a", None, (140, 50, 80)),
        ("scenes/library.png", "scene-ref", "scene_reference", None, "scene-library", (40, 90, 120)),
        ("styles/comic.png", "style-ref", "style_reference", None, None, (190, 140, 40)),
    ]
    if two_characters:
        source_specs.insert(
            1,
            ("characters/char-b.png", "char-b-ref", "identity_reference", "char-b", None, (40, 120, 70)),
        )
    for relative, asset_id, role, character_id, scene_id, color in source_specs:
        path = profile / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (1200, 600), color)
        ImageDraw.Draw(image).rectangle((20, 20, 200, 200), fill=color[::-1])
        image.save(path, format="PNG")
        assets.append(
            {
                "asset_id": asset_id,
                "role": role,
                "relative_path": relative,
                "sha256": _sha(path),
                "description": f"{asset_id} description",
                **({"character_id": character_id} if character_id else {}),
                **({"scene_id": scene_id} if scene_id else {}),
                "tags": ["canonical"],
            }
        )
    characters.append(
        {
            "character_id": "char-a",
            "name": "A",
            "description": "character A",
            "canonical_asset_id": "char-a-ref",
        }
    )
    if two_characters:
        characters.append(
            {
                "character_id": "char-b",
                "name": "B",
                "description": "character B",
                "canonical_asset_id": "char-b-ref",
            }
        )
    manifest = {
        "schema_name": "PresetAssetManifestV1",
        "schema_version": "1.0",
        "profile_id": "demo-v1",
        "default_scene_id": "scene-library",
        "default_style_id": "style-comic",
        "characters": characters,
        "scenes": [
            {
                "scene_id": "scene-library",
                "name": "library",
                "description": "night library",
                "canonical_asset_id": "scene-ref",
            }
        ],
        "styles": [
            {
                "style_id": "style-comic",
                "description": "comic style",
                "canonical_asset_id": "style-ref",
            }
        ],
        "assets": assets,
    }
    (profile / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return PresetAssetRepository(settings.asset_root, settings.scratch_root / "asset-cache")


def scene_job(request_id: str = "scene-job-1", panels: int = 1, two_characters: bool = False) -> SceneJobV1:
    characters = [{"character_id": "char-a", "action": "按住抽屉", "emotion": "紧张"}]
    if two_characters:
        characters.append({"character_id": "char-b", "action": "站在门边", "emotion": "疑惑"})
    payload = {
        "request_id": request_id,
        "project_id": "comic-a",
        "chapter_id": "chapter-1",
        "scene_id": "scene-1",
        "asset_profile_id": "demo-v1",
        "scene_context": {
            "summary": "信件丢失",
            "location": "藏书阁",
            "time_of_day": "夜晚",
            "atmosphere": "安静",
        },
        "panels": [
            {
                "panel_id": f"panel-{index:02d}",
                "sequence_no": index,
                "story_intent": f"推进剧情 {index}",
                "characters": characters,
                "dialogue": [{"speaker_id": "char-a", "text": "没什么"}],
                "constraints": [],
                "render_profile": ("landscape", "portrait", "square")[index % 3],
            }
            for index in range(panels)
        ],
    }
    return SceneJobV1.model_validate(payload)


def upstream_envelope(
    request_id: str = "scene-job-1",
    panels: int = 1,
    two_characters: bool = False,
) -> UpstreamSceneEnvelopeV1:
    job = scene_job(request_id, panels, two_characters)
    character_ids = ["char-a", *( ["char-b"] if two_characters else [])]
    payload = {
        "request_id": job.request_id,
        "project_id": job.project_id,
        "chapter_id": job.chapter_id,
        "scene_id": job.scene_id,
        "asset_profile_id": job.asset_profile_id,
        "characters": [
            {
                "character_id": character_id,
                "name": character_id,
                "appearance": f"{character_id} appearance",
                "clothing": [f"{character_id} clothing"],
            }
            for character_id in character_ids
        ],
        "scene": {
            "summary": job.scene_context.summary,
            "location_id": "scene-library",
            "location": job.scene_context.location,
            "time_of_day": job.scene_context.time_of_day,
            "atmosphere": job.scene_context.atmosphere,
        },
        "events": [
            {
                "event_id": f"event-{panel.sequence_no:02d}",
                "sequence_no": panel.sequence_no,
                "action": panel.story_intent,
                "actor_ids": [panel.characters[0].character_id],
            }
            for panel in job.panels
        ],
        "panels": [
            {
                "panel_id": panel.panel_id,
                "sequence_no": panel.sequence_no,
                "event_ids": [f"event-{panel.sequence_no:02d}"],
                "story_intent": panel.story_intent,
                "characters": [item.model_dump(mode="json") for item in panel.characters],
                "dialogue": [
                    {
                        "dialogue_id": f"dialogue-{panel.sequence_no:02d}-{index:02d}",
                        "speaker_id": item.speaker_id,
                        "text": item.text,
                    }
                    for index, item in enumerate(panel.dialogue)
                ],
                "constraints": panel.constraints,
                "render_profile": panel.render_profile.value,
            }
            for panel in job.panels
        ],
    }
    return UpstreamSceneEnvelopeV1.model_validate(payload)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
