from __future__ import annotations

import argparse
import json
from pathlib import Path

from anime_image_agent.upstream_contracts import MAPPING_AUDIT, UpstreamSceneEnvelopeV1, schema_snapshot_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the audit-only upstream envelope schema")
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.schema, args.audit, args.snapshot):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.schema.write_text(
        json.dumps(UpstreamSceneEnvelopeV1.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.audit.write_text(
        json.dumps(MAPPING_AUDIT.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.snapshot.write_text(schema_snapshot_sha256() + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
