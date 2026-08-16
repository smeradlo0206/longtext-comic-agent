from __future__ import annotations

import gc
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from .assets import AssetRepository, ResolvedAsset, select_panel_assets
from .config import PLANNER_MODEL_ID
from .scene_contracts import (
    AssetBindingV1,
    CharacterVisualStateV1,
    PanelVisualPlanV1,
    RegionV1,
    SceneJobV1,
    VisualPlanV1,
)


@dataclass(frozen=True, slots=True)
class PanelPlanningAssets:
    panel_id: str
    assets: tuple[ResolvedAsset, ...]


@dataclass(frozen=True, slots=True)
class ScenePlanningContext:
    job: SceneJobV1
    panel_assets: tuple[PanelPlanningAssets, ...]

    def assets_for(self, panel_id: str) -> tuple[ResolvedAsset, ...]:
        for item in self.panel_assets:
            if item.panel_id == panel_id:
                return item.assets
        raise KeyError(panel_id)


class VisualPlanner(Protocol):
    model_id: str

    def plan(self, context: ScenePlanningContext) -> VisualPlanV1: ...
    def close(self) -> None: ...


def assemble_planning_context(job: SceneJobV1, repository: AssetRepository) -> ScenePlanningContext:
    profile = repository.get_profile(job.asset_profile_id)
    selections: list[PanelPlanningAssets] = []
    for panel in sorted(job.panels, key=lambda item: item.sequence_no):
        assets = select_panel_assets(
            repository,
            job.asset_profile_id,
            [character.character_id for character in panel.characters],
            profile.default_scene_id,
        )
        selections.append(PanelPlanningAssets(panel.panel_id, tuple(assets)))
    return ScenePlanningContext(job, tuple(selections))


class FakeVisualPlanner:
    model_id = "fake-qwen2.5-vl-7b"

    def plan(self, context: ScenePlanningContext) -> VisualPlanV1:
        panels: list[PanelVisualPlanV1] = []
        placements = ("left", "right")
        for panel in sorted(context.job.panels, key=lambda item: item.sequence_no):
            states = [
                CharacterVisualStateV1(
                    character_id=character.character_id,
                    placement=placements[index],
                    action=character.action,
                    expression=character.emotion,
                    gaze="看向当前动作涉及的对象",
                )
                for index, character in enumerate(panel.characters)
            ]
            assets = context.assets_for(panel.panel_id)
            bindings = [_binding(asset, index + 1) for index, asset in enumerate(assets)]
            safe_zones = []
            if panel.dialogue:
                safe_zones = [RegionV1(x=0.62, y=0.05, width=0.33, height=0.25)]
            panels.append(
                PanelVisualPlanV1(
                    panel_id=panel.panel_id,
                    narrative_focus=panel.story_intent,
                    emotional_target="、".join(character.emotion for character in panel.characters) or "保持叙事氛围",
                    shot_size="medium",
                    camera_angle="eye_level",
                    camera_direction="镜头朝向主要人物，保持清晰空间关系",
                    characters=states,
                    foreground=[],
                    midground=[context.job.scene_context.location],
                    background=[context.job.scene_context.summary],
                    focal_point=panel.story_intent,
                    environment=context.job.scene_context.location,
                    lighting=context.job.scene_context.time_of_day or "符合场景的自然光线",
                    atmosphere=context.job.scene_context.atmosphere or "符合剧情的氛围",
                    dialogue_safe_zones=safe_zones,
                    asset_bindings=bindings,
                    required_elements=[character.action for character in panel.characters],
                    forbidden_elements=list(panel.constraints),
                )
            )
        return VisualPlanV1(request_id=context.job.request_id, planner_model_id=self.model_id, panels=panels)

    def close(self) -> None:
        return


class QwenVisualPlanner:
    model_id = PLANNER_MODEL_ID

    def __init__(self, model_path: Path | str = PLANNER_MODEL_ID, device: str = "cuda:0") -> None:
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        self.device = device
        self.processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=Path(str(model_path)).exists())
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            str(model_path),
            torch_dtype=torch.bfloat16,
            device_map={"": device},
            local_files_only=Path(str(model_path)).exists(),
        ).eval()

    def plan(self, context: ScenePlanningContext) -> VisualPlanV1:
        raw = self._generate(context, repair_source=None)
        try:
            plan = VisualPlanV1.model_validate(_extract_json(raw))
            _validate_plan_against_context(plan, context)
            return plan
        except Exception as first_error:
            repaired = self._generate(context, repair_source=f"{raw}\n校验错误：{first_error}")
            plan = VisualPlanV1.model_validate(_extract_json(repaired))
            _validate_plan_against_context(plan, context)
            return plan

    def _generate(self, context: ScenePlanningContext, repair_source: str | None) -> str:
        import torch

        content: list[dict[str, Any]] = []
        seen: set[str] = set()
        for selection in context.panel_assets:
            for asset in selection.assets:
                if asset.record.asset_id in seen or len(seen) >= 16:
                    continue
                seen.add(asset.record.asset_id)
                content.append({"type": "image", "image": asset.normalized_path})
        content.append({"type": "text", "text": _planner_prompt(context, repair_source)})
        messages = [{"role": "user", "content": content}]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images = [Image.open(item["image"]).convert("RGB") for item in content if item["type"] == "image"]
        inputs = self.processor(text=[text], images=images or None, padding=True, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            output_ids = self.model.generate(**inputs, max_new_tokens=24576, do_sample=False)
        trimmed = output_ids[:, inputs.input_ids.shape[1] :]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True)[0]

    def close(self) -> None:
        del self.model, self.processor
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except (ImportError, RuntimeError):
            pass


def _planner_prompt(context: ScenePlanningContext, repair_source: str | None) -> str:
    schema = VisualPlanV1.model_json_schema()
    input_payload = context.job.model_dump(mode="json")
    bindings = {
        item.panel_id: [
            {
                "asset_id": asset.record.asset_id,
                "purpose": _purpose(asset),
                "target_character_id": asset.record.character_id,
                "image_index": index + 1,
                "description": asset.record.description,
            }
            for index, asset in enumerate(item.assets)
        ]
        for item in context.panel_assets
    }
    template = _planner_output_template(context)
    panel_ids = [panel.panel_id for panel in sorted(context.job.panels, key=lambda item: item.sequence_no)]
    instruction = (
        "你是漫画视觉导演。为整个场景统一规划每个画格，输出且只输出一个满足 JSON Schema 的 JSON 对象，"
        "不要使用 Markdown 代码块，不要解释。输入图片全部是人物、场景或风格参考图，不是漫画画格；"
        f"输出 panels 必须恰好有 {len(panel_ids)} 项，顺序和 panel_id 必须严格为 {json.dumps(panel_ids, ensure_ascii=False)}。"
        "不得修改 request_id、panel_id、人物 ID、人物数量或给定 asset_bindings，也不得增加任何画格。"
        "请从给定输出模板开始，只填写视觉导演需要决定的语义字符串和字符串数组；模板中的固定 ID、"
        "asset_bindings、数组结构和 dialogue_safe_zones 不得改动。foreground、midground、background、"
        "required_elements、forbidden_elements 的每一项都必须是字符串，绝不能放入素材对象。"
        "所有 dialogue_safe_zones 均为 0 到 1 的归一化数值，并必须满足 x+width<=1、y+height<=1。"
        "对白只用于判断构图，图片本身不得出现文字。镜头要服务叙事，并保持跨格空间、服装和光线连续。"
    )
    prompt = (
        instruction
        + "\n场景请求：\n"
        + json.dumps(input_payload, ensure_ascii=False)
        + "\n固定素材绑定：\n"
        + json.dumps(bindings, ensure_ascii=False)
        + "\n必须遵循的输出模板：\n"
        + json.dumps(template, ensure_ascii=False)
        + "\nJSON Schema：\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    if repair_source is not None:
        prompt += (
            "\n上一份输出无法通过校验。只修复格式与字段，重新从输出模板生成完整 JSON，不要解释。"
            "特别检查 panels 数量、字符串数组类型以及安全区边界。上一份输出及校验错误如下：\n"
            + repair_source
        )
    return prompt + "\n现在只输出最终 JSON 对象。"


def _planner_output_template(context: ScenePlanningContext) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    for panel in sorted(context.job.panels, key=lambda item: item.sequence_no):
        panels.append(
            {
                "panel_id": panel.panel_id,
                "narrative_focus": panel.story_intent,
                "emotional_target": "填写目标情绪",
                "shot_size": "填写景别",
                "camera_angle": "填写机位",
                "camera_direction": "填写镜头方向",
                "characters": [
                    {
                        "character_id": character.character_id,
                        "placement": "填写画面位置",
                        "action": character.action,
                        "expression": character.emotion,
                        "gaze": "填写视线方向",
                    }
                    for character in panel.characters
                ],
                "foreground": [],
                "midground": [context.job.scene_context.location],
                "background": [context.job.scene_context.summary],
                "focal_point": panel.story_intent,
                "environment": context.job.scene_context.location,
                "lighting": context.job.scene_context.time_of_day or "填写光线",
                "atmosphere": context.job.scene_context.atmosphere or "填写气氛",
                "dialogue_safe_zones": (
                    [{"x": 0.62, "y": 0.05, "width": 0.33, "height": 0.25}]
                    if panel.dialogue
                    else []
                ),
                "asset_bindings": [
                    _binding(asset, index + 1).model_dump(mode="json")
                    for index, asset in enumerate(context.assets_for(panel.panel_id))
                ],
                "required_elements": [character.action for character in panel.characters],
                "forbidden_elements": list(panel.constraints),
            }
        )
    return {
        "schema_name": "VisualPlanV1",
        "schema_version": "1.0",
        "request_id": context.job.request_id,
        "planner_model_id": PLANNER_MODEL_ID,
        "panels": panels,
    }


def _validate_plan_against_context(plan: VisualPlanV1, context: ScenePlanningContext) -> None:
    if plan.request_id != context.job.request_id:
        raise ValueError("planner changed request_id")
    expected_panels = [panel.panel_id for panel in sorted(context.job.panels, key=lambda item: item.sequence_no)]
    actual_panels = [panel.panel_id for panel in plan.panels]
    if actual_panels != expected_panels:
        raise ValueError("planner changed panel set or order")
    intent_by_id = {panel.panel_id: panel for panel in context.job.panels}
    for panel in plan.panels:
        expected_characters = {item.character_id for item in intent_by_id[panel.panel_id].characters}
        actual_characters = {item.character_id for item in panel.characters}
        if actual_characters != expected_characters:
            raise ValueError(f"planner changed characters for {panel.panel_id}")
        expected_bindings = [
            _binding(asset, index + 1) for index, asset in enumerate(context.assets_for(panel.panel_id))
        ]
        if panel.asset_bindings != expected_bindings:
            raise ValueError(f"planner changed asset bindings for {panel.panel_id}")
        if intent_by_id[panel.panel_id].dialogue and not panel.dialogue_safe_zones:
            raise ValueError(f"planner omitted dialogue_safe_zones for {panel.panel_id}")


def _binding(asset: ResolvedAsset, index: int) -> AssetBindingV1:
    return AssetBindingV1(
        asset_id=asset.record.asset_id,
        purpose=_purpose(asset),
        target_character_id=asset.record.character_id,
        image_index=index,
    )


def _purpose(asset: ResolvedAsset) -> str:
    return {
        "identity_reference": "identity",
        "scene_reference": "scene",
        "style_reference": "style",
    }[asset.record.role]


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner output must be a JSON object")
    return payload
