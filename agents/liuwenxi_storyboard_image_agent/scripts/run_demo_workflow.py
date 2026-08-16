from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from anime_image_agent.api import create_app
from anime_image_agent.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.environ["RUN_ROOT"] = str(ROOT / "output" / "demo-runtime")
    os.environ["OUTPUT_ROOT"] = str(ROOT / "output" / "demo-output")
    os.environ["SCRATCH_ROOT"] = str(ROOT / "output" / "demo-scratch")
    os.environ["ASSET_ROOT"] = str(ROOT / "assets" / "presets")
    settings = Settings.from_environment()
    app = create_app(settings, backend="fake", start_coordinator=True)
    request_payload = json.loads(
        (ROOT / "examples" / "upstream_scene_envelope.valid.json").read_text(encoding="utf-8")
    )
    request_payload["request_id"] = f"demo-{int(time.time())}"

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        submission = client.post("/v1/scene-jobs", json=request_payload)
        submission.raise_for_status()
        request_id = submission.json()["request_id"]

        status_payload = None
        for _ in range(300):
            status_response = client.get(f"/v1/scene-jobs/{request_id}")
            status_response.raise_for_status()
            status_payload = status_response.json()
            if status_payload["status"] in {"SUCCEEDED", "PARTIAL_FAILED", "FAILED"}:
                break
            time.sleep(0.05)
        else:
            raise TimeoutError(f"scene job did not complete: {status_payload}")

        result_response = client.get(f"/v1/scene-jobs/{request_id}/result")
        result_response.raise_for_status()
        result = result_response.json()
        artifacts = []
        for panel in result["panels"]:
            artifact = panel.get("artifact")
            if artifact is None:
                continue
            download = client.get(artifact["url"])
            download.raise_for_status()
            downloaded = ROOT / "output" / "demo-output" / f"downloaded-{artifact['image_id']}.png"
            downloaded.write_bytes(download.content)
            artifacts.append(
                {
                    "panel_id": panel["panel_id"],
                    "image_id": artifact["image_id"],
                    "source_uri": artifact["uri"],
                    "downloaded_uri": str(downloaded.resolve()),
                    "sha256": artifact["sha256"],
                    "width": artifact["width"],
                    "height": artifact["height"],
                }
            )

    summary = {
        "backend": "fake",
        "note": "The striped artifact validates workflow mechanics; it is not a Qwen model image.",
        "live": {"status_code": live.status_code, "body": live.json()},
        "ready": {"status_code": ready.status_code, "body": ready.json()},
        "submission": {"status_code": submission.status_code, "body": submission.json()},
        "final_status": status_payload,
        "result_status": result_response.status_code,
        "scene_result": result,
        "downloaded_artifacts": artifacts,
    }
    summary_path = ROOT / "output" / "demo-output" / f"{request_id}-workflow-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
