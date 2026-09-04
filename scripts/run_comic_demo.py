"""Run the isolated, repeatable TXT-to-comic demo pipeline."""

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.demo.autonomous_image_pipeline import AutonomousImagePipeline
from comic_agent.demo.narrative_adapter import DemoNarrativeAdapter
from comic_agent.demo.pipeline import ComicDemoPipeline
from comic_agent.demo.production_runtime import ProductionDemoRuntime
from comic_agent.demo.timeline_adapter import DemoTimelineAdapter
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.storybible import ApprovedStoryBibleBundleV1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/demo"))
    parser.add_argument(
        "--provider-mode",
        choices=("real", "auto", "deterministic"),
        default="auto",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        choices=range(1, 4),
        default=3,
        help="maximum chunks per Narrative batch; the full document is always processed",
    )
    parser.add_argument("--skip-storybible-provider", action="store_true")
    parser.add_argument("--character-reference", type=Path)
    parser.add_argument("--scene-reference", type=Path)
    parser.add_argument(
        "--later-scene-reference",
        type=Path,
        help="optional second scene reference used for the latter half of the panels",
    )
    parser.add_argument(
        "--sanitize-opening-scene-reference",
        action="store_true",
        help="derive a clean-lintel copy of the opening gate reference before generation",
    )
    parser.add_argument(
        "--pages-per-reference",
        type=int,
        help="split each of two scene references across this many consecutive comic pages",
    )
    parser.add_argument(
        "--opening-scene-signage",
        help="exact text composited on the opening gate lintel after generation",
    )
    parser.add_argument(
        "--opening-scene-signage-font",
        type=Path,
        help="CJK font used for exact opening-gate signage",
    )
    parser.add_argument("--model-path", type=Path, default=Path("models/FLUX.2-klein-4B"))
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="stop after PanelPlan artifacts; by default the command also runs FLUX.2",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.output_dir, 0o700)
    if (
        not args.plan_only
        and args.character_reference is None
        and args.scene_reference is None
        and args.later_scene_reference is None
    ):
        parser.error(
            "automatic image generation requires --character-reference or --scene-reference"
        )
    if args.pages_per_reference is not None and args.later_scene_reference is None:
        parser.error("--pages-per-reference requires --scene-reference and --later-scene-reference")
    if args.opening_scene_signage is not None and args.scene_reference is None:
        parser.error("--opening-scene-signage requires --scene-reference")
    if args.opening_scene_signage_font is not None and args.opening_scene_signage is None:
        parser.error("--opening-scene-signage-font requires --opening-scene-signage")
    runtime = None
    try:
        if args.provider_mode != "deterministic":
            runtime = ProductionDemoRuntime(
                input_path=args.input,
                work_dir=args.output_dir / ".runtime",
                max_chunks=args.max_chunks,
            )
        pipeline = ComicDemoPipeline(
            curator=runtime.run_storybible if runtime else None,
            narrative_adapter=DemoNarrativeAdapter(runtime) if runtime else None,
            timeline_adapter=DemoTimelineAdapter(runtime) if runtime else None,
        )
        result = pipeline.run(
            input_path=args.input,
            output_root=args.output_dir,
            provider_mode=args.provider_mode,
            skip_storybible_provider=args.skip_storybible_provider,
        )
        if not args.plan_only:
            panels = TypeAdapter(list[PanelPlanV1]).validate_json(
                (result.artifact_dir / "panels.json").read_text(encoding="utf-8")
            )
            storybible_payload = json.loads(
                (result.artifact_dir / "storybible.json").read_text(encoding="utf-8")
            )
            storybible = ApprovedStoryBibleBundleV1.model_validate(storybible_payload["bundle"])
            image_result = AutonomousImagePipeline(
                model_path=args.model_path,
                offline=args.offline,
                width=args.width,
                height=args.height,
                steps=args.steps,
                device=args.device,
            ).run(
                source_path=args.input,
                artifact_dir=result.artifact_dir,
                panels=panels,
                storybible=storybible,
                character_reference=args.character_reference,
                scene_reference=args.scene_reference,
                later_scene_reference=args.later_scene_reference,
                sanitize_opening_scene_reference=args.sanitize_opening_scene_reference,
                pages_per_reference=args.pages_per_reference,
                opening_scene_signage=args.opening_scene_signage,
                opening_scene_signage_font=args.opening_scene_signage_font,
            )
            result.summary.update(
                {
                    "image_status": str(image_result.run.status),
                    "image_run_id": image_result.run.run_id,
                    "image_run_root": image_result.run.run_root,
                    "page_artifacts": [
                        artifact.model_dump(mode="json")
                        for artifact in image_result.run.page_artifacts
                    ],
                    "reference_bindings": image_result.reference_bindings,
                    "opening_scene_signage_overlays": image_result.signage_overlays,
                    "performance": (
                        image_result.run.performance.model_dump(mode="json")
                        if image_result.run.performance
                        else None
                    ),
                }
            )
            summary_path = result.artifact_dir / "summary.json"
            summary_path.write_text(
                json.dumps(result.summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.chmod(summary_path, 0o600)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False
            )
        )
        return 1
    finally:
        if runtime is not None:
            runtime.close()
    print(json.dumps(result.summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
