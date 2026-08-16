from __future__ import annotations

import hashlib
import json

from .assets import AssetRepository
from .config import BASE_NEGATIVE_PROMPT, RENDER_PROFILES
from .planning import ScenePlanningContext
from .scene_contracts import GenerationSpecV1, ReferenceInputV1, SceneJobV1, VisualPlanV1, panel_seed


class GenerationCompiler:
    def __init__(self, repository: AssetRepository) -> None:
        self.repository = repository

    def compile(
        self,
        job: SceneJobV1,
        context: ScenePlanningContext,
        visual_plan: VisualPlanV1,
    ) -> list[GenerationSpecV1]:
        plans = {panel.panel_id: panel for panel in visual_plan.panels}
        specs: list[GenerationSpecV1] = []
        for panel in sorted(job.panels, key=lambda item: item.sequence_no):
            plan = plans[panel.panel_id]
            selected = context.assets_for(panel.panel_id)
            references = [
                ReferenceInputV1(
                    asset_id=asset.record.asset_id,
                    purpose=binding.purpose,
                    target_character_id=binding.target_character_id,
                    image_index=binding.image_index,
                    uri=asset.normalized_path,
                    sha256=asset.normalized_sha256,
                )
                for binding, asset in zip(plan.asset_bindings, selected, strict=True)
            ]
            positive = _positive_prompt(plan)
            negative = _negative_prompt(plan.forbidden_elements)
            prompt_hash = hashlib.sha256(
                json.dumps(
                    {"positive": positive, "negative": negative, "references": [item.asset_id for item in references]},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            width, height = RENDER_PROFILES[panel.render_profile.value]
            specs.append(
                GenerationSpecV1(
                    request_id=job.request_id,
                    panel_id=panel.panel_id,
                    prompt_id=_prompt_id(job.request_id, panel.panel_id),
                    positive_prompt=positive,
                    negative_prompt=negative,
                    references=references,
                    render_profile=panel.render_profile,
                    width=width,
                    height=height,
                    seed=panel_seed(job.request_id, panel.panel_id),
                    prompt_sha256=prompt_hash,
                    used_asset_ids=[item.asset_id for item in references],
                )
            )
        return specs


def _positive_prompt(plan) -> str:
    reference_rules = []
    for binding in plan.asset_bindings:
        if binding.purpose == "identity":
            reference_rules.append(
                f"图{binding.image_index}是角色{binding.target_character_id}的身份参考，严格保持脸型、发型、服装和配色"
            )
        elif binding.purpose == "scene":
            reference_rules.append(f"图{binding.image_index}是场景参考，保持空间元素和环境特征")
        else:
            reference_rules.append(f"图{binding.image_index}是画风参考，只继承绘画语言和色彩质感")
    characters = "；".join(
        f"{item.character_id}位于{item.placement}，{item.action}，表情{item.expression}，视线{item.gaze}"
        for item in plan.characters
    )
    safe_zones = "；".join(
        f"画面归一化区域x={zone.x:.2f}, y={zone.y:.2f}, w={zone.width:.2f}, h={zone.height:.2f}保持简洁留白"
        for zone in plan.dialogue_safe_zones
    )
    layers = (
        f"前景：{'、'.join(plan.foreground) or '无明显遮挡'}；"
        f"中景：{'、'.join(plan.midground) or '人物与主要动作'}；"
        f"背景：{'、'.join(plan.background) or plan.environment}"
    )
    sections = [
        "生成一幅完整的新漫画分镜底图，不要拼贴参考图，不要生成文字、字幕、气泡或边框。",
        "。".join(reference_rules),
        f"叙事重点：{plan.narrative_focus}；目标情绪：{plan.emotional_target}",
        f"镜头：{plan.shot_size}，{plan.camera_angle}，{plan.camera_direction}；视觉焦点：{plan.focal_point}",
        f"人物：{characters}" if characters else "画面中不出现主要人物",
        f"构图层次：{layers}",
        f"环境：{plan.environment}；光线：{plan.lighting}；氛围：{plan.atmosphere}",
        f"必须出现：{'、'.join(plan.required_elements)}" if plan.required_elements else "",
        f"对白安全区：{safe_zones}" if safe_zones else "",
    ]
    return "。".join(section.strip("。") for section in sections if section) + "。"


def _negative_prompt(forbidden: list[str]) -> str:
    suffix = "，".join(forbidden)
    return BASE_NEGATIVE_PROMPT + (f" {suffix}" if suffix else "")


def _prompt_id(request_id: str, panel_id: str) -> str:
    candidate = f"{request_id}.{panel_id}.g1"
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"prompt-{digest}"
