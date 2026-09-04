"""Fast, auditable visual QA for generated comic panels."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from comic_agent.schemas.image_workflow import PlannedReference, PlannedShot, VisualQASettings
from comic_agent.schemas.qa import QAResultV1, RepairPlanV1


def _palette_histogram(image: Image.Image) -> np.ndarray:
    pixels = np.asarray(image.convert("RGB").resize((64, 64)), dtype=np.uint8)
    bins = (pixels // 32).reshape(-1, 3).astype(np.int64)
    indexes = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    histogram = np.bincount(indexes, minlength=512).astype(np.float64)
    norm = float(np.linalg.norm(histogram))
    return histogram / norm if norm else histogram


def _reference_similarity(image: Image.Image, references: list[PlannedReference]) -> float:
    if not references:
        return 1.0
    target = _palette_histogram(image)
    scores: list[float] = []
    for reference in references:
        with Image.open(reference.path) as source:
            scores.append(float(np.dot(target, _palette_histogram(source))))
    return sum(scores) / len(scores)


class PanelVisualQA:
    """Evaluate cheap objective signals before accepting a generated panel."""

    evaluator_id = "local-objective-visual-qa-v1"

    def evaluate(
        self,
        *,
        image_path: Path,
        target_id: str,
        evaluation_index: int,
        expected_size: tuple[int, int],
        references: list[PlannedReference],
        settings: VisualQASettings,
    ) -> QAResultV1:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
            pixels = np.asarray(image, dtype=np.float32) / 255.0
            gray = pixels.mean(axis=2)
            dynamic_range = float(np.percentile(gray, 95) - np.percentile(gray, 5))
            horizontal = float(np.abs(np.diff(gray, axis=1)).mean())
            vertical = float(np.abs(np.diff(gray, axis=0)).mean())
            edge_energy = (horizontal + vertical) / 2.0
            reference_similarity = _reference_similarity(image, references)
            actual_size = image.size

        scores = {
            "dimensions": 1.0 if actual_size == expected_size else 0.0,
            "dynamic_range": round(dynamic_range, 6),
            "edge_energy": round(edge_energy, 6),
            "reference_similarity": round(reference_similarity, 6),
        }
        failures: list[str] = []
        issues: list[dict[str, object]] = []
        checks = (
            (actual_size != expected_size, "dimensions", expected_size, actual_size),
            (
                dynamic_range < settings.min_dynamic_range,
                "dynamic_range",
                settings.min_dynamic_range,
                dynamic_range,
            ),
            (
                edge_energy < settings.min_edge_energy,
                "edge_energy",
                settings.min_edge_energy,
                edge_energy,
            ),
            (
                reference_similarity < settings.min_reference_similarity,
                "reference_similarity",
                settings.min_reference_similarity,
                reference_similarity,
            ),
        )
        for failed, check, threshold, actual in checks:
            if not failed:
                continue
            failures.append(check)
            issues.append(
                {
                    "check": check,
                    "expected": threshold,
                    "actual": actual,
                    "scope": "full_panel",
                }
            )
        fingerprint = hashlib.sha256(
            f"{target_id}:{evaluation_index}:{image_path.stat().st_size}".encode()
        ).hexdigest()[:16]
        return QAResultV1(
            qa_result_id=f"qa-{fingerprint}",
            target_type="comic_panel",
            target_id=target_id,
            check_scores=scores,
            hard_failures=failures,
            issues=issues,
            passed=not failures,
            evaluated_by=self.evaluator_id,
        )

    def repair_plan(
        self,
        *,
        shot: PlannedShot,
        result: QAResultV1,
        repair_index: int,
    ) -> tuple[PlannedShot, RepairPlanV1]:
        instructions = {
            "dimensions": "严格输出指定宽高，画面必须完整铺满画布",
            "dynamic_range": "提高主体与背景的明暗层次，避免空白、灰雾和低对比画面",
            "edge_energy": "补足人物五官、手部、服装和环境的清晰结构细节",
            "reference_similarity": "重新核对所有参考图，恢复角色、服装和场景的关键配色特征",
        }
        repair_instruction = "；".join(
            instructions[item] for item in result.hard_failures if item in instructions
        )
        repaired = shot.model_copy(
            update={
                "prompt": (
                    shot.prompt
                    + "\n选择性修复要求：只重绘当前这一格，不改变故事时刻。"
                    + repair_instruction
                    + "。"
                )
            }
        )
        plan = RepairPlanV1(
            repair_plan_id=f"repair-{shot.shot_id}-{repair_index:02d}",
            target_id=shot.shot_id,
            repair_type="FULL_PANEL_REGENERATE",
            target_region=None,
            instruction=repair_instruction,
            max_attempts=1,
        )
        return repaired, plan
