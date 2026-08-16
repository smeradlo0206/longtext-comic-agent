from __future__ import annotations

import argparse
import json
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a SceneResultV1 into reviewable visual plans, specs, and timing summaries")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    panels = result["panels"]
    visual_panels = [item["visual_plan"] for item in panels]
    planner_ids = {item.get("planner_model_id") for item in visual_panels if item.get("planner_model_id")}
    visual_plan = {
        "schema_name": "VisualPlanV1",
        "schema_version": "1.0",
        "request_id": result["request_id"],
        "planner_model_id": next(iter(planner_ids), "Qwen/Qwen2.5-VL-7B-Instruct"),
        "panels": visual_panels,
    }
    write_json(args.output / "visual-plan.json", visual_plan)
    write_json(
        args.output / "generation-specs.json",
        {
            "schema_name": "GenerationSpecCollectionV1",
            "request_id": result["request_id"],
            "items": [item["generation_spec"] for item in panels],
        },
    )
    metadata = [item["metadata"] for item in panels if item.get("metadata")]
    write_json(
        args.output / "timings.json",
        {
            "request_id": result["request_id"],
            "submitted_at": result["submitted_at"],
            "completed_at": result.get("completed_at"),
            "panel_generation_seconds": {
                item["panel_id"]: item["metadata"]["generation_seconds"]
                for item in panels
                if item.get("metadata")
            },
            "gpu_pairs": {item["panel_id"]: item["metadata"]["gpu_ids"] for item in panels if item.get("metadata")},
            "max_parallel_generation_seconds": max((item["generation_seconds"] for item in metadata), default=None),
        },
    )


if __name__ == "__main__":
    main()
