from __future__ import annotations

import heapq
from pathlib import Path

from .models import (
    IdentityAnchorSpec,
    PlannedIdentityAnchor,
    PlannedReference,
    PlannedShot,
    ReferenceCatalog,
    ReferenceRole,
    Shot,
    ShotReference,
    StoryboardRequest,
    WorkflowJob,
    WorkflowPlan,
)

ROLE_LABELS: dict[ReferenceRole, str] = {
    "character_identity": "角色身份",
    "character_outfit": "角色服装",
    "scene": "场景",
    "prop": "道具",
    "style": "补充画风",
    "composition": "构图",
    "continuity": "镜头连续性",
}

SLOT_RENDERERS: dict[ReferenceRole, str] = {
    "character_identity": "图{index}中的角色",
    "character_outfit": "图{index}中的服装",
    "scene": "图{index}中的场景",
    "prop": "图{index}中的道具",
    "style": "图{index}中的视觉风格",
    "composition": "图{index}中的构图关系",
    "continuity": "图{index}中的上一镜头状态",
}

def ordered_references(job: WorkflowJob, shot: Shot) -> list[ShotReference]:
    selection_order = {
        item.asset_id: index for index, item in enumerate(job.selected_assets)
    }
    return sorted(shot.references, key=lambda item: selection_order[item.asset_id])


def render_shot_prompt(prompt: str, references: list[ShotReference]) -> str:
    rendered = prompt
    replacements = {
        reference.slot: SLOT_RENDERERS[reference.role].format(index=index)
        for index, reference in enumerate(references, start=1)
    }
    for slot in sorted(replacements, key=len, reverse=True):
        rendered = rendered.replace(slot, replacements[slot])
    return rendered


def compile_prompt(job: WorkflowJob, shot_index: int) -> str:
    shot = job.shots[shot_index]
    references = ordered_references(job, shot)
    anchored_asset_ids = {item.asset_id for item in job.identity_anchors}
    reference_lines = []
    for index, reference in enumerate(references, start=1):
        if reference.asset_id in anchored_asset_ids:
            reference_lines.append(
                f"图{index}（Image {index}）是本次运行统一生成的彩色角色身份锚点："
                f"{reference.purpose}；所有镜头必须保持其脸型、五官、发型、发色、"
                "服装、体型和上色方案。"
            )
        else:
            reference_lines.append(
                f"图{index}（Image {index}）仅作为{ROLE_LABELS[reference.role]}参考："
                f"{reference.purpose}。"
            )
    if shot.continuity_from:
        continuity_index = len(references) + 1
        if shot.continuity_crop:
            reference_lines.append(
                f"图{continuity_index}（Image {continuity_index}）是从镜头 "
                f"{shot.continuity_from} 的已确认成图裁出的彩色人物身份锚点："
                "严格保持其中人物的脸型、五官、发型、发色、服装、配饰、体型"
                "和上色方案；忽略裁剪图中的姿势、构图和残留背景，场所、动作和"
                "人物数量完全以当前分镜为准。"
            )
        else:
            reference_lines.append(
                f"图{continuity_index}（Image {continuity_index}）是镜头 "
                f"{shot.continuity_from} 的已确认成图，仅作为镜头连续性参考："
                "严格保持重复出现人物的脸型、发型、服装和体型，以及场景布局、"
                "家具位置、色彩与光线；不得继承上一镜头的动作或当前分镜未指定的"
                "人物，当前分镜的场所、人物数量和动作具有最高优先级。"
            )
    if not reference_lines:
        reference_lines.append("无静态参考图；严格依据当前分镜文本生成。")
    sections = [
        f"视觉风格：{job.comic_style.rstrip('。')}。",
        "生成一张全新的单幅场景插画，画面从边缘到边缘连续完整。",
        "参考图绑定：",
        *reference_lines,
        (
            "全局保持项（只用于连续性约束，不表示当前画面中要同时出现的内容）："
            f"{job.global_prompt}"
        ),
        "只画当前分镜明确指定的一个时刻，不得提前或回顾全局保持项中的其他时刻。",
        f"当前分镜：{render_shot_prompt(shot.prompt, references)}",
    ]
    if job.quality_constraints:
        sections.append(
            "项目级保持项（仅约束当前镜头实际出现的角色与物体，不要求全部同时入画）："
            + "；".join(job.quality_constraints)
            + "。"
        )
    return "\n".join(sections)


def compile_identity_anchor_prompt(
    job: WorkflowJob,
    anchor: IdentityAnchorSpec,
) -> str:
    """Compile one isolated color-character normalization task."""

    label = anchor.display_name or anchor.entity_id
    return "\n".join(
        [
            f"视觉风格：{job.comic_style.rstrip('。')}。",
            "图1（Image 1）是唯一角色身份来源。",
            f"为角色“{label}”创建一张统一彩色身份设定锚点：{anchor.description}。",
            "画面恰好只有这一名角色，站立全身，正面稍三分之四视角，自然中性姿势。",
            "严格保留源图的脸型、五官、发型、体型、服装轮廓和辨识度，并完成稳定上色。",
            "使用干净浅灰背景、均匀中性光，不画场景、道具、其他人物、文字、水印或分格。",
        ]
    )


def build_execution_order(shots: list[Shot]) -> list[str]:
    by_id = {shot.shot_id: shot for shot in shots}
    position = {shot.shot_id: index for index, shot in enumerate(shots)}
    indegree = {shot.shot_id: 0 for shot in shots}
    dependents: dict[str, list[str]] = {shot.shot_id: [] for shot in shots}

    for shot in shots:
        dependency = shot.continuity_from
        if dependency is None:
            continue
        if dependency not in by_id:
            raise ValueError(
                f"shot {shot.shot_id} has unknown continuity_from: {dependency}"
            )
        if len(shot.references) >= 4:
            raise ValueError(
                f"shot {shot.shot_id} exceeds the four-image limit when continuity is added"
            )
        indegree[shot.shot_id] += 1
        dependents[dependency].append(shot.shot_id)

    ready = [
        (position[shot_id], shot_id)
        for shot_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _, shot_id = heapq.heappop(ready)
        ordered.append(shot_id)
        for dependent in dependents[shot_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (position[dependent], dependent))

    if len(ordered) != len(shots):
        cycle = [shot_id for shot_id, degree in indegree.items() if degree > 0]
        raise ValueError(f"continuity_from contains a cycle: {cycle}")
    return ordered


def validate_storyboard_handoff(
    request: StoryboardRequest,
    job: WorkflowJob,
) -> None:
    mismatches: list[str] = []
    if request.job_id != job.job_id:
        mismatches.append("job_id")
    if request.script != job.source_script:
        mismatches.append("script")
    if request.comic_style != job.comic_style:
        mismatches.append("comic_style")
    if request.global_prompt != job.global_prompt:
        mismatches.append("global_prompt")
    if request.quality_constraints != job.quality_constraints:
        mismatches.append("quality_constraints")
    if request.selected_assets != job.selected_assets:
        mismatches.append("selected_assets")
    if mismatches:
        raise ValueError(
            "storyboard output changed locked request fields: " + ", ".join(mismatches)
        )


def build_plan(workspace: Path, job: WorkflowJob, catalog: ReferenceCatalog) -> WorkflowPlan:
    workspace = workspace.resolve()
    by_id = {item.asset_id: item for item in catalog.references}
    selected_by_id = {item.asset_id: item for item in job.selected_assets}
    missing_selected = [
        item.asset_id for item in job.selected_assets if item.asset_id not in by_id
    ]
    if missing_selected:
        raise ValueError(f"selected_assets contains unknown asset IDs: {missing_selected}")
    if job.reference_policy.mode == "APPROVED_LIBRARY":
        violations: list[str] = []
        for selected in job.selected_assets:
            catalog_reference = by_id[selected.asset_id]
            reasons: list[str] = []
            if catalog_reference.lifecycle != "approved":
                reasons.append("not approved")
            if catalog_reference.entity_id != selected.entity_id:
                reasons.append("entity mismatch")
            if catalog_reference.intended_role != selected.role:
                reasons.append("role mismatch")
            if (
                job.reference_policy.require_canonical
                and not catalog_reference.is_canonical
            ):
                reasons.append("not canonical")
            if reasons:
                violations.append(f"{selected.asset_id} ({', '.join(reasons)})")
        if violations:
            raise ValueError(
                "selected_assets violates APPROVED_LIBRARY policy: " + "; ".join(violations)
            )
    execution_order = build_execution_order(job.shots)

    planned_anchors: list[PlannedIdentityAnchor] = []
    for anchor in job.identity_anchors:
        catalog_item = by_id[anchor.asset_id]
        selected_item = selected_by_id[anchor.asset_id]
        source_reference = PlannedReference(
            image_index=1,
            slot=anchor.slot,
            asset_id=anchor.asset_id,
            entity_id=anchor.entity_id,
            role=selected_item.role,
            purpose=anchor.description,
            path=(workspace / catalog_item.relative_path).resolve(),
        )
        planned_anchors.append(
            PlannedIdentityAnchor(
                anchor_id=anchor.anchor_id,
                slot=anchor.slot,
                asset_id=anchor.asset_id,
                entity_id=anchor.entity_id,
                prompt=compile_identity_anchor_prompt(job, anchor),
                source_reference=source_reference,
                seed=anchor.seed,
                width=anchor.width,
                height=anchor.height,
            )
        )

    planned: list[PlannedShot] = []
    for shot_index, shot in enumerate(job.shots):
        references = ordered_references(job, shot)
        resolved: list[PlannedReference] = []
        for image_index, reference in enumerate(references, start=1):
            catalog_item = by_id[reference.asset_id]
            selected_item = selected_by_id[reference.asset_id]
            resolved.append(
                PlannedReference(
                    image_index=image_index,
                    slot=reference.slot,
                    asset_id=reference.asset_id,
                    entity_id=selected_item.entity_id,
                    role=reference.role,
                    purpose=reference.purpose,
                    path=(workspace / catalog_item.relative_path).resolve(),
                )
            )
        seed = shot.seed if shot.seed is not None else job.generation.seed + shot_index
        planned.append(
            PlannedShot(
                shot_id=shot.shot_id,
                prompt=compile_prompt(job, shot_index),
                references=resolved,
                continuity_from=shot.continuity_from,
                continuity_crop=shot.continuity_crop,
                continuity_image_index=(
                    len(resolved) + 1 if shot.continuity_from else None
                ),
                seed=seed,
            )
        )
    return WorkflowPlan(
        job_id=job.job_id,
        model_id=job.generation.model_id,
        identity_anchors=planned_anchors,
        shots=planned,
        execution_order=execution_order,
        contact_sheet=job.contact_sheet,
    )
