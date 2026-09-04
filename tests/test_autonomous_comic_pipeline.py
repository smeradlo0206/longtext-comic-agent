"""Regression coverage for the unattended demo-to-FLUX handoff."""

import json
import stat
from pathlib import Path

from PIL import Image
from pydantic import TypeAdapter

from comic_agent.demo.autonomous_image_pipeline import AutonomousImagePipeline
from comic_agent.demo.pipeline import ComicDemoPipeline
from comic_agent.demo.production_runtime import ProductionDemoRuntime
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.storybible import ApprovedStoryBibleBundleV1


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_production_runtime_collects_the_full_document_beyond_batch_limit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "long.txt"
    source.write_text(
        "\n\n".join(f"第{index}段" + "校园迎新活动正在进行" * 180 for index in range(5)),
        encoding="utf-8",
    )

    runtime = ProductionDemoRuntime(
        input_path=source,
        work_dir=tmp_path / "private-runtime",
        max_chunks=1,
    )
    try:
        assert len(runtime.chunk_ids) > runtime.max_chunks
        assert _mode(runtime.database_path.parent) == 0o700
        assert _mode(runtime.database_path) == 0o600
    finally:
        runtime.close()


def test_autonomous_image_pipeline_registers_binds_and_enqueues_both_references(
    tmp_path: Path,
) -> None:
    source = tmp_path / "story.txt"
    source.write_text(
        "Lin arrives at the university gate. 志愿者说：“欢迎来到中国科大！” "
        "Mira shows Lin the registration desk.",
        encoding="utf-8",
    )
    planned = ComicDemoPipeline().run(
        input_path=source,
        output_root=tmp_path / "planning",
        provider_mode="deterministic",
    )
    panels = TypeAdapter(list[PanelPlanV1]).validate_json(
        (planned.artifact_dir / "panels.json").read_text(encoding="utf-8")
    )
    storybible_payload = json.loads(
        (planned.artifact_dir / "storybible.json").read_text(encoding="utf-8")
    )
    storybible = ApprovedStoryBibleBundleV1.model_validate(storybible_payload["bundle"])
    character = tmp_path / "character.png"
    scene = tmp_path / "scene.png"
    Image.new("RGB", (32, 64), "red").save(character)
    Image.new("RGB", (64, 32), "blue").save(scene)

    result = AutonomousImagePipeline(
        model_path=tmp_path / "unused-model",
        width=256,
        height=256,
        steps=1,
    ).run(
        source_path=source,
        artifact_dir=planned.artifact_dir,
        panels=panels,
        storybible=storybible,
        character_reference=character,
        scene_reference=scene,
        execute=False,
    )

    assert str(result.run.status) == "QUEUED"
    assert {binding["role"] for binding in result.reference_bindings} == {"style", "scene"}
    assert "no approved panel character" in result.reference_bindings[0]["reason"]
    assert all(
        {reference.role for reference in shot.references} == {"style", "scene"}
        for shot in result.run.manifest.workflow_job.shots
    )
    assert result.run.manifest.request.dialogue_layout.enabled is True
    assert result.run.manifest.request.visual_qa.max_auto_repairs == 3
    assert result.run.manifest.proposal.panels[0].panel.text_overlays[0].text == (
        "欢迎来到中国科大！"
    )
    assert "构图要求" in result.run.manifest.workflow_job.shots[0].prompt
    assert "欢迎来到中国科大！" not in (result.run.manifest.workflow_job.shots[0].prompt)
    assert "做出自然交流的表情和手势" in (result.run.manifest.workflow_job.shots[0].prompt)
    assert "单幅场景插画" in result.run.manifest.prompt_specs[0].provider_prompt
    assert "欢迎来到中国科大！" not in (result.run.manifest.prompt_specs[0].provider_prompt)
    assert _mode(planned.artifact_dir) == 0o700
    for path in planned.artifact_dir.rglob("*"):
        assert _mode(path) == (0o700 if path.is_dir() else 0o600)


def test_autonomous_image_pipeline_routes_two_scene_references_by_story_half(
    tmp_path: Path,
) -> None:
    source = tmp_path / "story.txt"
    source.write_text(
        "新生走到校门。志愿者上前迎接。两人走进校园。"
        "老师递交材料。新生在校内休息。傍晚她走向教学楼。",
        encoding="utf-8",
    )
    planned = ComicDemoPipeline().run(
        input_path=source,
        output_root=tmp_path / "planning",
        provider_mode="deterministic",
    )
    panels = TypeAdapter(list[PanelPlanV1]).validate_json(
        (planned.artifact_dir / "panels.json").read_text(encoding="utf-8")
    )
    storybible_payload = json.loads(
        (planned.artifact_dir / "storybible.json").read_text(encoding="utf-8")
    )
    storybible = ApprovedStoryBibleBundleV1.model_validate(storybible_payload["bundle"])
    opening = tmp_path / "opening.png"
    later = tmp_path / "later.png"
    Image.new("RGB", (100, 60), "red").save(opening)
    Image.new("RGB", (100, 60), "green").save(later)

    result = AutonomousImagePipeline(
        model_path=tmp_path / "unused-model", width=256, height=256, steps=1
    ).run(
        source_path=source,
        artifact_dir=planned.artifact_dir,
        panels=panels,
        storybible=storybible,
        character_reference=None,
        scene_reference=opening,
        later_scene_reference=later,
        sanitize_opening_scene_reference=True,
        execute=False,
    )

    shots = result.run.manifest.workflow_job.shots
    split_index = (len(shots) + 1) // 2
    opening_id = next(
        item["asset_id"]
        for item in result.reference_bindings
        if item["reason"] == "explicitly routed to the opening half"
    )
    later_id = next(
        item["asset_id"]
        for item in result.reference_bindings
        if item["reason"] == "explicitly routed to the later half"
    )
    assert all(
        [reference.asset_id for reference in shot.references] == [opening_id]
        for shot in shots[:split_index]
    )
    assert all(
        [reference.asset_id for reference in shot.references] == [later_id]
        for shot in shots[split_index:]
    )
    assert result.signage_overlays == []
    assert all(
        forbidden not in prompt.provider_prompt.lower()
        for prompt in result.run.manifest.prompt_specs
        for forbidden in ("speech bubble", "dialogue", "caption", "气泡", "对白", "字幕")
    )


def test_page_counts_allocate_two_pages_to_each_scene_reference() -> None:
    assert AutonomousImagePipeline._page_panel_counts(
        panel_count=6,
        pages_per_reference=2,
        has_two_scene_references=True,
    ) == [2, 1, 2, 1]
