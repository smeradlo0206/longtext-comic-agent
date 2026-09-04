from datetime import UTC, datetime
from pathlib import Path

import pytest

from flux2_agent.models import (
    ContinuityCrop,
    ReferenceCatalog,
    ReferenceImage,
    ReferenceLibraryPolicy,
    SelectedAsset,
    Shot,
    ShotReference,
    StoryboardRequest,
    WorkflowJob,
)
from flux2_agent.planning import (
    build_execution_order,
    build_plan,
    validate_storyboard_handoff,
)


def reference(asset_id: str) -> ReferenceImage:
    return ReferenceImage(
        asset_id=asset_id,
        filename=f"{asset_id}.png",
        relative_path=f"inputs/references/{asset_id}.png",
        sha256="a" * 64,
        mime_type="image/png",
        width=64,
        height=64,
        bytes=100,
    )


def catalog() -> ReferenceCatalog:
    return ReferenceCatalog(
        references=[reference("wechat-001"), reference("wechat-002")]
    )


def selected_assets() -> list[SelectedAsset]:
    return [
        SelectedAsset(
            slot="CHAR_A",
            asset_id="wechat-001",
            entity_id="character.lead",
            role="character_identity",
            description="lead character identity",
        ),
        SelectedAsset(
            slot="SCENE_A",
            asset_id="wechat-002",
            entity_id="scene.tea_room",
            role="scene",
            description="tea room location",
        ),
    ]


def job() -> WorkflowJob:
    return WorkflowJob(
        job_id="test-job",
        source_script="CHAR_A enters SCENE_A.",
        comic_style="精致彩色漫画，清晰墨线",
        global_prompt="global direction",
        quality_constraints=["single continuous panel"],
        selected_assets=selected_assets(),
        shots=[
            Shot(
                shot_id="shot-001",
                prompt="CHAR_A enters SCENE_A.",
                references=[
                    ShotReference(
                        slot="SCENE_A",
                        asset_id="wechat-002",
                        role="scene",
                        purpose="spatial layout",
                    ),
                    ShotReference(
                        slot="CHAR_A",
                        asset_id="wechat-001",
                        role="character_identity",
                        purpose="face and hair identity",
                    ),
                ],
            )
        ],
    )


def request() -> StoryboardRequest:
    current = job()
    return StoryboardRequest(
        job_id=current.job_id,
        script=current.source_script,
        comic_style=current.comic_style,
        global_prompt=current.global_prompt,
        quality_constraints=current.quality_constraints,
        selected_assets=current.selected_assets,
    )


def test_plan_binds_selected_assets_in_locked_order(tmp_path: Path) -> None:
    plan = build_plan(tmp_path, job(), catalog())
    shot = plan.shots[0]

    assert shot.prompt.startswith("视觉风格：精致彩色漫画，清晰墨线。")
    assert "图1（Image 1）仅作为角色身份参考" in shot.prompt
    assert "图2（Image 2）仅作为场景参考" in shot.prompt
    assert "生成一张全新的单幅场景插画" in shot.prompt
    assert "图1中的角色 enters 图2中的场景" in shot.prompt
    assert "CHAR_A" not in shot.prompt
    assert [item.asset_id for item in shot.references] == [
        "wechat-001",
        "wechat-002",
    ]
    assert [item.image_index for item in shot.references] == [1, 2]
    assert shot.references[0].entity_id == "character.lead"
    assert plan.execution_order == ["shot-001"]


def test_plan_compiles_identity_anchor_and_marks_panel_reference(tmp_path: Path) -> None:
    payload = job().model_dump(mode="json")
    payload["identity_anchors"] = [
        {
            "anchor_id": "anchor-lead",
            "slot": "CHAR_A",
            "asset_id": "wechat-001",
            "entity_id": "character.lead",
            "description": "lead character identity",
            "display_name": "林夏",
            "seed": 101,
            "width": 512,
            "height": 768,
        }
    ]

    plan = build_plan(tmp_path, WorkflowJob.model_validate(payload), catalog())

    assert len(plan.identity_anchors) == 1
    anchor = plan.identity_anchors[0]
    assert anchor.anchor_id == "anchor-lead"
    assert anchor.source_reference.path == (
        tmp_path / "inputs/references/wechat-001.png"
    )
    assert anchor.width == 512
    assert anchor.height == 768
    assert "画面恰好只有这一名角色" in anchor.prompt
    assert "统一生成的彩色角色身份锚点" in plan.shots[0].prompt


def test_plan_resolves_continuity_dependencies_before_story_order(
    tmp_path: Path,
) -> None:
    payload = job().model_dump(mode="json")
    payload["shots"][0]["continuity_from"] = "shot-002"
    payload["shots"].append(
        {
            **payload["shots"][0],
            "shot_id": "shot-002",
            "continuity_from": None,
        }
    )

    plan = build_plan(tmp_path, WorkflowJob.model_validate(payload), catalog())

    assert [shot.shot_id for shot in plan.shots] == ["shot-001", "shot-002"]
    assert plan.execution_order == ["shot-002", "shot-001"]
    assert plan.shots[0].continuity_image_index == 3
    assert "图3（Image 3）是镜头 shot-002 的已确认成图" in plan.shots[0].prompt


def test_plan_compiles_cropped_identity_anchor(tmp_path: Path) -> None:
    payload = job().model_dump(mode="json")
    payload["shots"][0]["continuity_from"] = "shot-002"
    payload["shots"][0]["continuity_crop"] = {
        "left": 0.0,
        "top": 0.1,
        "right": 0.5,
        "bottom": 1.0,
    }
    payload["shots"].append(
        {
            **payload["shots"][0],
            "shot_id": "shot-002",
            "continuity_from": None,
            "continuity_crop": None,
        }
    )

    plan = build_plan(tmp_path, WorkflowJob.model_validate(payload), catalog())

    assert plan.shots[0].continuity_crop == ContinuityCrop(
        left=0.0,
        top=0.1,
        right=0.5,
        bottom=1.0,
    )
    assert "彩色人物身份锚点" in plan.shots[0].prompt
    assert "忽略裁剪图中的姿势、构图和残留背景" in plan.shots[0].prompt


def test_shot_rejects_crop_without_continuity_source() -> None:
    payload = job().shots[0].model_dump(mode="json")
    payload["continuity_crop"] = {
        "left": 0.0,
        "top": 0.0,
        "right": 0.5,
        "bottom": 1.0,
    }

    with pytest.raises(ValueError, match="requires continuity_from"):
        Shot.model_validate(payload)


def test_derived_shot_can_use_only_continuity_reference(tmp_path: Path) -> None:
    payload = job().model_dump(mode="json")
    payload["shots"][0]["references"] = []
    payload["shots"][0]["continuity_from"] = "shot-002"
    payload["shots"][0]["continuity_crop"] = {
        "left": 0.25,
        "top": 0.25,
        "right": 0.75,
        "bottom": 0.75,
    }
    payload["shots"].append(
        {
            **job().shots[0].model_dump(mode="json"),
            "shot_id": "shot-002",
        }
    )

    plan = build_plan(tmp_path, WorkflowJob.model_validate(payload), catalog())

    assert plan.shots[0].references == []
    assert plan.shots[0].continuity_image_index == 1
    assert "图1（Image 1）" in plan.shots[0].prompt


def test_root_shot_allows_text_only_generation() -> None:
    payload = job().shots[0].model_dump(mode="json")
    payload["references"] = []

    shot = Shot.model_validate(payload)

    assert shot.references == []


def test_workflow_job_reads_v21_without_identity_anchors() -> None:
    payload = job().model_dump(mode="json")
    payload["schema_version"] = "2.1"
    payload.pop("identity_anchors")

    restored = WorkflowJob.model_validate(payload)

    assert restored.schema_version == "2.1"
    assert restored.identity_anchors == []


def test_execution_order_rejects_continuity_cycle() -> None:
    payload = job().shots[0].model_dump(mode="json")
    first = Shot.model_validate(
        {**payload, "shot_id": "shot-001", "continuity_from": "shot-002"}
    )
    second = Shot.model_validate(
        {**payload, "shot_id": "shot-002", "continuity_from": "shot-001"}
    )

    with pytest.raises(ValueError, match="contains a cycle"):
        build_execution_order([first, second])


def test_execution_order_rejects_unknown_continuity_source() -> None:
    payload = job().shots[0].model_dump(mode="json")
    shot = Shot.model_validate({**payload, "continuity_from": "missing-shot"})

    with pytest.raises(ValueError, match="unknown continuity_from"):
        build_execution_order([shot])


def test_execution_order_reserves_one_reference_for_continuity() -> None:
    references = [
        ShotReference(
            slot=f"REF_{index}",
            asset_id=f"asset-{index}",
            role="style",
            purpose="test",
        )
        for index in range(1, 5)
    ]
    parent = Shot(shot_id="parent", prompt="parent", references=[references[0]])
    child = Shot(
        shot_id="child",
        prompt="child",
        references=references,
        continuity_from="parent",
    )

    with pytest.raises(ValueError, match="four-image limit"):
        build_execution_order([parent, child])


def test_job_rejects_reference_outside_selected_assets() -> None:
    payload = job().model_dump(mode="json")
    payload["shots"][0]["references"][0]["asset_id"] = "wechat-999"

    with pytest.raises(ValueError, match="outside selected_assets"):
        WorkflowJob.model_validate(payload)


def test_plan_rejects_unknown_selected_asset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown asset IDs"):
        build_plan(tmp_path, job(), ReferenceCatalog(references=[reference("wechat-001")]))


def test_plan_enforces_approved_canonical_reference_library(tmp_path: Path) -> None:
    approved = ReferenceImage.model_validate(
        reference("wechat-001").model_dump(mode="python")
        | {
            "lifecycle": "approved",
            "entity_id": "character.lead",
            "intended_role": "character_identity",
            "is_canonical": True,
            "approved_at": datetime.now(UTC),
        }
    )
    approved_scene = ReferenceImage.model_validate(
        reference("wechat-002").model_dump(mode="python")
        | {
            "lifecycle": "approved",
            "entity_id": "scene.tea_room",
            "intended_role": "scene",
            "is_canonical": True,
            "approved_at": datetime.now(UTC),
        }
    )
    strict_job = job().model_copy(
        update={"reference_policy": ReferenceLibraryPolicy(mode="APPROVED_LIBRARY")}
    )

    plan = build_plan(
        tmp_path,
        strict_job,
        ReferenceCatalog(references=[approved, approved_scene]),
    )
    assert plan.shots[0].references[0].asset_id == "wechat-001"

    with pytest.raises(ValueError, match="not approved"):
        build_plan(tmp_path, strict_job, catalog())


def test_handoff_accepts_locked_fields() -> None:
    validate_storyboard_handoff(request(), job())


def test_handoff_rejects_changed_asset_selection() -> None:
    payload = request().model_dump(mode="json")
    payload["selected_assets"][0]["entity_id"] = "character.changed"
    changed = StoryboardRequest.model_validate(payload)

    with pytest.raises(ValueError, match="selected_assets"):
        validate_storyboard_handoff(changed, job())


def test_dimensions_must_be_divisible_by_sixteen() -> None:
    payload = job().model_dump(mode="json")
    payload["generation"]["width"] = 1001

    with pytest.raises(ValueError, match="divisible by 16"):
        WorkflowJob.model_validate(payload)
