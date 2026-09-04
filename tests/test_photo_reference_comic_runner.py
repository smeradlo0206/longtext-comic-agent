"""Coverage for the one-command TXT-and-reference-photo comic entrypoint."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_photo_reference_comic.py"


def _image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (32, 32), color).save(path)


def test_one_command_compiles_four_photo_routed_pages_without_model_calls(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("清晨，新生来到校园报到。\n\n志愿者提供问询指引服务。", encoding="utf-8")
    gate = tmp_path / "gate.png"
    building = tmp_path / "building.png"
    character = tmp_path / "character.png"
    _image(gate, (40, 90, 140))
    _image(building, (140, 90, 40))
    _image(character, (90, 40, 140))
    output = tmp_path / "output"
    command = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(source),
        "--reference",
        str(gate),
        "--reference",
        str(building),
        "--character-reference",
        str(character),
        "--output-dir",
        str(output),
        "--width",
        "256",
        "--height",
        "256",
        "--steps",
        "1",
        "--compile-only",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["status"] == "QUEUED"
    assert summary["panel_count"] == 24
    assert summary["page_count"] == 4
    assert summary["references"] == [
        {
            "asset_id": "asset-001",
            "entity_id": "visual-reference.scene-01",
            "role": "scene",
            "page_orders": [0, 1],
        },
        {
            "asset_id": "asset-002",
            "entity_id": "visual-reference.scene-02",
            "role": "scene",
            "page_orders": [2, 3],
        },
        {
            "asset_id": "asset-003",
            "entity_id": "visual-reference.character-style",
            "role": "style",
            "page_orders": [0, 1, 2, 3],
        },
    ]

    repeated = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(repeated.stdout)["run_id"] == summary["run_id"]

    panels = json.loads((output / "panels.json").read_text(encoding="utf-8"))
    assert len(panels) == 24
    source_text = source.read_text(encoding="utf-8")
    assert all(panel["evidence_refs"][0]["quote_text"] in source_text for panel in panels)

    queue_file = next((output / ".runtime/image-queue/pending").glob("*.json"))
    queued = json.loads(queue_file.read_text(encoding="utf-8"))["job"]
    assert [shot["references"][0]["asset_id"] for shot in queued["shots"]] == (
        ["asset-001"] * 12 + ["asset-002"] * 12
    )
    assert all(shot["references"][-1]["asset_id"] == "asset-003" for shot in queued["shots"])
    assert "Do not render readable text" in queued["global_prompt"]
