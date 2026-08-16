from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from anime_image_agent.assets import PresetAssetRepository, select_panel_assets
from anime_image_agent.io_utils import sha256_file
from anime_image_agent.compiler import GenerationCompiler
from anime_image_agent.planning import (
    FakeVisualPlanner,
    _planner_output_template,
    _planner_prompt,
    assemble_planning_context,
)
from anime_image_agent.scene_contracts import (
    GenerationSpecV1,
    RENDER_PROFILES,
    SceneJobV1,
    SceneResultV1,
    VisualPlanV1,
    panel_seed,
)

from .scene_helpers import make_asset_repository, make_scene_settings, scene_job


def test_scene_contract_limits_and_unknown_fields() -> None:
    payload = scene_job().model_dump(mode="json")
    payload["panels"][0]["characters"] *= 3
    payload["unknown"] = True
    with pytest.raises(ValidationError) as caught:
        SceneJobV1.model_validate(payload)
    locations = {tuple(item["loc"]) for item in caught.value.errors()}
    assert ("panels", 0, "characters") in locations
    assert ("unknown",) in locations


def test_asset_normalization_and_selection_priority(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings, two_characters=True)
    selected = select_panel_assets(repository, "demo-v1", ["char-a", "char-b"])
    assert [item.record.asset_id for item in selected] == ["char-a-ref", "char-b-ref", "scene-ref"]
    with Image.open(selected[0].normalized_path) as image:
        assert image.mode == "RGB"
        assert max(image.size) == 1024


def test_transparent_assets_are_flattened_on_neutral_background(tmp_path) -> None:
    source = tmp_path / "transparent.png"
    image = Image.new("RGBA", (20, 20), (180, 20, 40, 0))
    for x in range(5, 15):
        for y in range(5, 15):
            image.putpixel((x, y), (180, 20, 40, 255))
    image.save(source)
    repository = PresetAssetRepository(tmp_path, tmp_path / "cache")
    normalized = repository._normalize(source, sha256_file(source))
    with Image.open(normalized) as flattened:
        assert flattened.mode == "RGB"
        assert flattened.getpixel((0, 0)) == (238, 238, 238)
        assert flattened.getpixel((10, 10)) == (180, 20, 40)


def test_asset_path_escape_and_checksum_are_rejected(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    manifest = settings.asset_root / "demo-v1" / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["assets"][0]["relative_path"] = "../outside.png"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    repository = type(repository)(settings.asset_root, settings.scratch_root / "other-cache")
    with pytest.raises(ValueError, match="escapes"):
        repository.resolve_asset("demo-v1", "char-a-ref")

    repository = make_asset_repository(settings)
    source = settings.asset_root / "demo-v1" / "characters" / "char-a.png"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        repository.resolve_asset("demo-v1", "char-a-ref")


def test_compiler_is_deterministic_and_supports_three_profiles(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    job = scene_job(panels=3)
    context = assemble_planning_context(job, repository)
    plan = FakeVisualPlanner().plan(context)
    specs = GenerationCompiler(repository).compile(job, context, plan)
    assert [(spec.width, spec.height) for spec in specs] == [
        RENDER_PROFILES["landscape"],
        RENDER_PROFILES["portrait"],
        RENDER_PROFILES["square"],
    ]
    assert specs[0].seed == panel_seed(job.request_id, job.panels[0].panel_id)
    assert "图1是角色char-a" in specs[0].positive_prompt
    assert "对白安全区" in specs[0].positive_prompt
    assert GenerationCompiler(repository).compile(job, context, plan) == specs


def test_planner_prompt_pins_structural_fields_and_safe_zones(tmp_path) -> None:
    settings = make_scene_settings(tmp_path)
    repository = make_asset_repository(settings)
    job = scene_job(panels=3)
    context = assemble_planning_context(job, repository)

    template = _planner_output_template(context)
    assert [panel["panel_id"] for panel in template["panels"]] == [
        panel.panel_id for panel in job.panels
    ]
    assert template["panels"][0]["characters"][0]["character_id"] == "char-a"
    assert template["panels"][0]["asset_bindings"] == [
        {
            "asset_id": "char-a-ref",
            "purpose": "identity",
            "target_character_id": "char-a",
            "image_index": 1,
        },
        {
            "asset_id": "scene-ref",
            "purpose": "scene",
            "target_character_id": None,
            "image_index": 2,
        },
        {
            "asset_id": "style-ref",
            "purpose": "style",
            "target_character_id": None,
            "image_index": 3,
        },
    ]
    zone = template["panels"][0]["dialogue_safe_zones"][0]
    assert zone["x"] + zone["width"] <= 1
    assert zone["y"] + zone["height"] <= 1

    prompt = _planner_prompt(context, repair_source="invalid output")
    assert "输入图片全部是人物、场景或风格参考图，不是漫画画格" in prompt
    assert "输出 panels 必须恰好有 3 项" in prompt
    assert "绝不能放入素材对象" in prompt
    assert "重新从输出模板生成完整 JSON" in prompt


def test_committed_scene_schemas_match_runtime_models() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {
        "scene-job-v1.schema.json": SceneJobV1.model_json_schema(),
        "visual-plan-v1.schema.json": VisualPlanV1.model_json_schema(),
        "generation-spec-v1.schema.json": GenerationSpecV1.model_json_schema(),
        "scene-result-v1.schema.json": SceneResultV1.model_json_schema(),
    }
    for filename, schema in expected.items():
        assert json.loads((root / "schemas" / filename).read_text(encoding="utf-8")) == schema
