from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


MATERIAL_WEIGHTS = {
    "identity_consistency": 0.35,
    "target_compliance": 0.35,
    "clothing_hair_consistency": 0.15,
    "structural_quality": 0.10,
    "asset_reusability": 0.05,
}
COMIC_WEIGHTS = {
    "identity_consistency": 0.25,
    "character_count": 0.10,
    "action_compliance": 0.20,
    "object_continuity": 0.15,
    "scene_consistency": 0.15,
    "structural_quality": 0.15,
}
HARD_DEFECT_FIELDS = (
    "extra_person",
    "extra_limb_or_finger",
    "broken_face_or_body",
    "unwanted_text",
    "watermark_or_logo",
)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        value = json.loads(cleaned[cleaned.find("{") : cleaned.rfind("}") + 1])
    if not isinstance(value, dict):
        raise ValueError("evaluation response must be a JSON object")
    return value


def evaluation_prompt(item: dict, mode: str) -> str:
    weights = MATERIAL_WEIGHTS if mode == "material" else COMIC_WEIGHTS
    labels = "\n".join(f"图{index + 1}: {label}" for index, label in enumerate(item["image_labels"]))
    hard_defects = list(HARD_DEFECT_FIELDS)
    return (
        "你是严格的漫画图像质检员。逐项比较输入图片，只依据可见证据评分，不要因为画面好看而忽略身份或动作错误。"
        "每个 score 必须是 0 到 100 的整数；100 表示完全满足，0 表示完全失败。只输出 JSON，不要 Markdown。\n"
        f"图片顺序：\n{labels}\n任务要求：{item['task']}\n"
        f"评分字段及权重：{json.dumps(weights, ensure_ascii=False)}\n"
        "输出格式：{\"scores\":{每个评分字段:整数},\"hard_defects\":{每个硬缺陷字段:true或false},"
        "\"observations\":[不超过6条具体可见事实],\"identity_drift\":[不超过4条身份漂移事实],"
        "\"verdict\":\"一句话结论\"}。"
        f"hard_defects 必须恰好包含：{json.dumps(hard_defects, ensure_ascii=False)}。"
    )


def run_model(model, processor, item: dict, mode: str, device: str, correction: bool = False) -> tuple[str, dict]:
    import torch

    content = [
        {"type": "image", "image": path}
        for path in item["images"]
    ]
    prompt = evaluation_prompt(item, mode)
    if correction:
        prompt += "\n前一次输出未通过格式校验。请逐字使用要求的字段名，hard_defects 五个字段不得缺失。"
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    chat = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images = [Image.open(path).convert("RGB") for path in item["images"]]
    inputs = processor(text=[chat], images=images, padding=True, return_tensors="pt").to(device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
    trimmed = output[:, inputs.input_ids.shape[1] :]
    raw = processor.batch_decode(trimmed, skip_special_tokens=True)[0]
    return raw, extract_json(raw)


def normalize_hard_defects(value: object) -> dict[str, bool]:
    if isinstance(value, list):
        unknown = set(value) - set(HARD_DEFECT_FIELDS)
        if unknown:
            raise ValueError(f"unknown hard defect names: {sorted(unknown)}")
        return {key: key in value for key in HARD_DEFECT_FIELDS}
    if not isinstance(value, dict) or set(value) != set(HARD_DEFECT_FIELDS):
        raise ValueError("hard_defects must contain exactly the required fields")
    normalized = {}
    for key in HARD_DEFECT_FIELDS:
        item = value[key]
        if isinstance(item, bool):
            normalized[key] = item
        elif isinstance(item, str) and item.lower() in {"true", "false"}:
            normalized[key] = item.lower() == "true"
        else:
            raise ValueError(f"invalid hard defect value for {key}: {item!r}")
    return normalized


def validate_and_score(payload: dict, mode: str) -> tuple[dict, dict[str, bool], float, bool]:
    weights = MATERIAL_WEIGHTS if mode == "material" else COMIC_WEIGHTS
    scores = payload.get("scores", {})
    normalized = {}
    for key in weights:
        value = scores.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ValueError(f"invalid score for {key}: {value!r}")
        normalized[key] = value
    defects = normalize_hard_defects(payload.get("hard_defects"))
    total = round(sum(normalized[key] * weight for key, weight in weights.items()), 2)
    has_hard_defect = any(defects.values())
    return normalized, defects, total, has_hard_defect


def main() -> None:
    parser = argparse.ArgumentParser(description="Run auditable Qwen2.5-VL material or comic scoring")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("material", "comic"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    config = json.loads(args.config.read_text(encoding="utf-8"))
    processor = AutoProcessor.from_pretrained(str(args.model), local_files_only=True)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        str(args.model), torch_dtype=torch.bfloat16, device_map={"": args.device}, local_files_only=True
    ).eval()
    results = []
    for item in config["items"]:
        failed_outputs = []
        for attempt in range(1, args.max_attempts + 1):
            raw, payload = run_model(model, processor, item, args.mode, args.device, correction=attempt > 1)
            try:
                scores, defects, total, has_hard_defect = validate_and_score(payload, args.mode)
                break
            except ValueError as exc:
                failed_outputs.append({"attempt": attempt, "error": str(exc), "raw_model_output": raw})
        else:
            results.append(
                {
                    "item_id": item["item_id"],
                    "task": item["task"],
                    "images": item["images"],
                    "eligible": False,
                    "evaluation_error": "model output failed schema validation",
                    "failed_outputs": failed_outputs,
                }
            )
            continue
        results.append(
            {
                "item_id": item["item_id"],
                "task": item["task"],
                "images": item["images"],
                "scores": scores,
                "weighted_total": total,
                "hard_defects": defects,
                "eligible": total >= 80 and not has_hard_defect,
                "observations": payload.get("observations", []),
                "identity_drift": payload.get("identity_drift", []),
                "verdict": payload.get("verdict", ""),
                "evaluation_attempt": attempt,
                "failed_outputs": failed_outputs,
                "raw_model_output": raw,
            }
        )
    report = {
        "schema_name": "QwenVLImageEvaluationV1",
        "mode": args.mode,
        "model_id": "Qwen/Qwen2.5-VL-7B-Instruct",
        "weights": MATERIAL_WEIGHTS if args.mode == "material" else COMIC_WEIGHTS,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "items": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
