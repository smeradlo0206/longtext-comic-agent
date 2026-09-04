import json
import stat
from pathlib import Path

from PIL import Image, ImageDraw

from flux2_agent.models import (
    MODEL_ID,
    ContactSheetSettings,
    ContinuityCrop,
    IdentityAnchorSpec,
    PlannedIdentityAnchor,
    PlannedReference,
    PlannedShot,
    SelectedAsset,
    Shot,
    ShotReference,
    VisualQASettings,
    WorkflowJob,
    WorkflowPlan,
)
from flux2_agent.workflow import (
    apply_identity_anchor_paths,
    copy_reference_images,
    prepare_continuity_reference,
    run_workflow,
)


def planned_reference(source: Path) -> PlannedReference:
    return PlannedReference(
        image_index=1,
        slot="CHAR_A",
        asset_id="wechat-004",
        entity_id="character.tea_lead",
        role="character_identity",
        purpose="identity",
        path=source,
    )


def detailed_image(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for offset in range(0, size[0], 16):
        draw.rectangle((offset, 0, min(offset + 7, size[0] - 1), size[1]), fill="black")
    return image


def test_copy_reference_images_places_unique_inputs_in_run_root(tmp_path: Path) -> None:
    source = tmp_path / "source.JPG"
    source.write_bytes(b"reference image")
    run_root = tmp_path / "run"
    run_root.mkdir()
    plan = WorkflowPlan(
        job_id="test-job",
        model_id=MODEL_ID,
        shots=[
            PlannedShot(
                shot_id="shot-001",
                prompt="first",
                references=[planned_reference(source)],
                seed=1,
            ),
            PlannedShot(
                shot_id="shot-002",
                prompt="second",
                references=[planned_reference(source)],
                seed=2,
            ),
        ],
        execution_order=["shot-001", "shot-002"],
    )

    references = copy_reference_images(run_root, plan)

    destination = run_root / "reference-wechat-004.jpg"
    assert destination.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert references == [{"asset_id": "wechat-004", "file": destination.name}]


def test_workflow_generates_anchor_then_replaces_panel_character_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), "white").save(source)
    selected = SelectedAsset(
        slot="CHAR_A",
        asset_id="wechat-004",
        entity_id="character.lead",
        role="character_identity",
        description="lead identity",
    )
    anchor_spec = IdentityAnchorSpec(
        anchor_id="anchor-lead",
        slot=selected.slot,
        asset_id=selected.asset_id,
        entity_id=selected.entity_id,
        description=selected.description,
        seed=100,
        width=256,
        height=320,
    )
    reference = planned_reference(source).model_copy(
        update={"entity_id": selected.entity_id}
    )
    panel = PlannedShot(
        shot_id="panel-001",
        prompt="panel",
        references=[reference],
        seed=200,
    )
    job = WorkflowJob(
        job_id="anchor-test",
        source_script="lead enters",
        comic_style="完整上色的精致漫画",
        global_prompt="one panel",
        selected_assets=[selected],
        identity_anchors=[anchor_spec],
        shots=[
            Shot(
                shot_id=panel.shot_id,
                prompt=panel.prompt,
                references=[
                    ShotReference(
                        slot=selected.slot,
                        asset_id=selected.asset_id,
                        role=selected.role,
                        purpose=selected.description,
                    )
                ],
            )
        ],
    )
    plan = WorkflowPlan(
        job_id=job.job_id,
        model_id=MODEL_ID,
        identity_anchors=[
            PlannedIdentityAnchor(
                anchor_id=anchor_spec.anchor_id,
                slot=anchor_spec.slot,
                asset_id=anchor_spec.asset_id,
                entity_id=anchor_spec.entity_id,
                prompt="single color character",
                source_reference=reference,
                seed=anchor_spec.seed,
                width=anchor_spec.width,
                height=anchor_spec.height,
            )
        ],
        shots=[panel],
        execution_order=[panel.shot_id],
    )
    calls: list[tuple[str, Path]] = []

    class FakeBackend:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def generate(
            self,
            shot: PlannedShot,
            seed: int,
            *,
            continuity_path: Path | None = None,
        ) -> Image.Image:
            calls.append((shot.shot_id, shot.references[0].path))
            return Image.new("RGB", (8, 8), "red")

    monkeypatch.setattr("flux2_agent.workflow.Flux2Backend", FakeBackend)

    run_root = run_workflow(job, plan, tmp_path / "runs")
    anchor_path = run_root / "identity-anchor-anchor-lead.png"

    assert calls == [
        ("anchor-lead", source),
        ("panel-001", anchor_path),
    ]
    assert anchor_path.is_file()
    effective = apply_identity_anchor_paths(panel, {selected.entity_id: anchor_path})
    assert effective.references[0].path == anchor_path
    result = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
    assert result["schema_version"] == "2.2"
    assert result["identity_anchors"][0]["status"] == "succeeded"
    assert result["shots"][0]["reference_bindings"][0]["identity_anchor_id"] == (
        "anchor-lead"
    )
    assert stat.S_IMODE(run_root.stat().st_mode) == 0o700
    for filename in (
        "request.json",
        "plan.json",
        "result.json",
        "reference-wechat-004.png",
        "identity-anchor-anchor-lead.png",
        "panel-001.png",
    ):
        assert stat.S_IMODE((run_root / filename).stat().st_mode) == 0o600


def test_workflow_uses_parent_output_and_builds_sheet_in_story_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), "white").save(source)
    selected = SelectedAsset(
        slot="CHAR_A",
        asset_id="wechat-004",
        entity_id="character.lead",
        role="character_identity",
        description="lead",
    )
    reference = ShotReference(
        slot="CHAR_A",
        asset_id="wechat-004",
        role="character_identity",
        purpose="identity",
    )
    job = WorkflowJob(
        job_id="continuity-test",
        source_script="child follows parent",
        comic_style="完整上色的精致漫画",
        global_prompt="one location",
        selected_assets=[selected],
        contact_sheet=ContactSheetSettings(columns=2, filename="sheet.png"),
        shots=[
            Shot(
                shot_id="child",
                prompt="child",
                references=[reference],
                continuity_from="parent",
            ),
            Shot(shot_id="parent", prompt="parent", references=[reference]),
        ],
    )
    planned = planned_reference(source)
    plan = WorkflowPlan(
        job_id=job.job_id,
        model_id=MODEL_ID,
        shots=[
            PlannedShot(
                shot_id="child",
                prompt="child",
                references=[planned],
                continuity_from="parent",
                continuity_image_index=2,
                seed=1,
            ),
            PlannedShot(
                shot_id="parent",
                prompt="parent",
                references=[planned],
                seed=2,
            ),
        ],
        execution_order=["parent", "child"],
        contact_sheet=job.contact_sheet,
    )
    calls: list[tuple[str, Path | None]] = []

    class FakeBackend:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def generate(
            self,
            shot: PlannedShot,
            seed: int,
            *,
            continuity_path: Path | None = None,
        ) -> Image.Image:
            calls.append((shot.shot_id, continuity_path))
            color = "red" if shot.shot_id == "child" else "blue"
            return Image.new("RGB", (8, 8), color)

    monkeypatch.setattr("flux2_agent.workflow.Flux2Backend", FakeBackend)

    run_root = run_workflow(job, plan, tmp_path / "runs")

    assert calls[0] == ("parent", None)
    assert calls[1] == ("child", run_root / "parent.png")
    result = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert [shot["shot_id"] for shot in result["shots"]] == ["child", "parent"]
    assert result["shots"][0]["continuity"]["file"] == "parent.png"
    assert result["contact_sheet"]["file"] == "sheet.png"
    for filename in ("parent.png", "child.png", "sheet.png"):
        assert stat.S_IMODE((run_root / filename).stat().st_mode) == 0o600
    with Image.open(run_root / "sheet.png") as sheet:
        assert sheet.size == (16, 8)
        assert sheet.getpixel((2, 2)) == (255, 0, 0)
        assert sheet.getpixel((10, 2)) == (0, 0, 255)


def test_prepare_continuity_reference_crops_normalized_box(tmp_path: Path) -> None:
    parent = tmp_path / "parent.png"
    image = Image.new("RGB", (20, 10), "blue")
    try:
        for x in range(10, 20):
            for y in range(10):
                image.putpixel((x, y), (0, 128, 0))
        image.save(parent)
    finally:
        image.close()

    result = prepare_continuity_reference(
        tmp_path,
        parent,
        "child",
        ContinuityCrop(left=0.5, top=0.0, right=1.0, bottom=1.0),
    )

    assert result == tmp_path / "continuity-parent-for-child.png"
    assert stat.S_IMODE(result.stat().st_mode) == 0o600
    with Image.open(result) as cropped:
        assert cropped.size == (10, 10)
        assert cropped.getpixel((5, 5)) == (0, 128, 0)


def test_prepare_continuity_reference_keeps_full_parent(tmp_path: Path) -> None:
    parent = tmp_path / "parent.png"
    parent.write_bytes(b"parent")

    assert prepare_continuity_reference(tmp_path, parent, "child", None) == parent


def test_visual_qa_repairs_only_the_failed_panel(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    detailed_image((256, 256)).save(source)
    selected = SelectedAsset(
        slot="CHAR_A",
        asset_id="wechat-004",
        entity_id="character.lead",
        role="character_identity",
        description="lead",
    )
    shot_reference = ShotReference(
        slot=selected.slot,
        asset_id=selected.asset_id,
        role=selected.role,
        purpose="identity",
    )
    job = WorkflowJob(
        job_id="qa-repair-test",
        source_script="two panels",
        comic_style="完整上色的精致漫画",
        global_prompt="one image per panel",
        selected_assets=[selected],
        generation={"width": 256, "height": 256, "steps": 1, "attempts": 1},
        visual_qa=VisualQASettings(
            enabled=True,
            min_dynamic_range=0.2,
            min_edge_energy=0.01,
            max_auto_repairs=1,
        ),
        shots=[
            Shot(shot_id="bad-panel", prompt="bad", references=[shot_reference]),
            Shot(shot_id="good-panel", prompt="good", references=[shot_reference]),
        ],
    )
    reference = planned_reference(source).model_copy(
        update={"entity_id": selected.entity_id}
    )
    plan = WorkflowPlan(
        job_id=job.job_id,
        model_id=MODEL_ID,
        shots=[
            PlannedShot(
                shot_id="bad-panel", prompt="bad", references=[reference], seed=10
            ),
            PlannedShot(
                shot_id="good-panel", prompt="good", references=[reference], seed=20
            ),
        ],
        execution_order=["bad-panel", "good-panel"],
    )
    calls: list[str] = []

    class FakeBackend:
        settings = job.generation

        def generate(
            self,
            shot: PlannedShot,
            seed: int,
            *,
            continuity_path: Path | None = None,
        ) -> Image.Image:
            calls.append(shot.shot_id)
            if shot.shot_id == "bad-panel" and "选择性修复要求" not in shot.prompt:
                return Image.new("RGB", (256, 256), "white")
            return detailed_image((256, 256))

    run_root = run_workflow(
        job,
        plan,
        tmp_path / "runs",
        backend=FakeBackend(),  # type: ignore[arg-type]
    )
    result = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
    records = {item["shot_id"]: item for item in result["shots"]}

    assert calls == ["bad-panel", "bad-panel", "good-panel"]
    assert len(records["bad-panel"]["qa_history"]) == 2
    assert records["bad-panel"]["qa_history"][-1]["passed"] is True
    assert len(records["bad-panel"]["repairs"]) == 1
    assert len(records["good-panel"]["attempts"]) == 1
    assert (run_root / "qa-rejected-bad-panel-01.png").is_file()
    assert result["performance"]["single_image_seconds"] is not None
    assert result["performance"]["within_budget"] is True
