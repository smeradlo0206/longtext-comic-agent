from __future__ import annotations

import argparse
import json
from pathlib import Path

from anime_image_agent.upstream_contracts import (
    MAPPING_AUDIT,
    UpstreamSceneEnvelopeV1,
    envelope_sha256,
    map_envelope_to_scene_job,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and deterministically map an audit envelope to production SceneJobV1")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--scene-job", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    envelope = UpstreamSceneEnvelopeV1.model_validate_json(args.input.read_text(encoding="utf-8"))
    scene_job = map_envelope_to_scene_job(envelope)
    args.scene_job.parent.mkdir(parents=True, exist_ok=True)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.scene_job.write_text(
        json.dumps(scene_job.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.audit.write_text(
        json.dumps(
            {
                "source_sha256": envelope_sha256(envelope),
                "source": str(args.input.resolve()),
                "target": str(args.scene_job.resolve()),
                "mapping": MAPPING_AUDIT.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
