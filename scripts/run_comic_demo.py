"""Run the isolated, repeatable TXT-to-comic demo pipeline."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.demo.narrative_adapter import DemoNarrativeAdapter
from comic_agent.demo.pipeline import ComicDemoPipeline
from comic_agent.demo.production_runtime import ProductionDemoRuntime
from comic_agent.demo.timeline_adapter import DemoTimelineAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/demo"))
    parser.add_argument(
        "--provider-mode",
        choices=("real", "auto", "deterministic"),
        default="auto",
    )
    parser.add_argument("--max-chunks", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--skip-storybible-provider", action="store_true")
    args = parser.parse_args()
    runtime = None
    try:
        if args.provider_mode != "deterministic":
            runtime = ProductionDemoRuntime(
                input_path=args.input,
                work_dir=args.output_dir / ".runtime",
                max_chunks=args.max_chunks,
            )
        result = ComicDemoPipeline(
            narrative_adapter=DemoNarrativeAdapter(runtime) if runtime else None,
            timeline_adapter=DemoTimelineAdapter(runtime) if runtime else None,
        ).run(
            input_path=args.input,
            output_root=args.output_dir,
            provider_mode=args.provider_mode,
            skip_storybible_provider=args.skip_storybible_provider,
        )
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
