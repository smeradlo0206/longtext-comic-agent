from __future__ import annotations

import importlib.util
from pathlib import Path
import math

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def load_renderer():
    spec = importlib.util.spec_from_file_location("render_comic_dialogue", ROOT / "scripts" / "render_comic_dialogue.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bubble_rendering_has_stable_canvas_and_layout(tmp_path) -> None:
    renderer = load_renderer()
    image = Image.new("RGB", (1664, 928), (120, 170, 130))
    layout = renderer.render_bubble(
        image,
        "站住！你拿了什么？",
        {"x": 0.04, "y": 0.04, "width": 0.36, "height": 0.22},
        (1200, 600),
        renderer.DEFAULT_FONT,
    )
    destination = tmp_path / "bubble.png"
    image.save(destination)
    assert Image.open(destination).size == (1664, 928)
    assert "".join(layout["lines"]) == "站住！你拿了什么？"
    assert layout["font_size"] >= 18
    bubble_center = ((layout["bubble_bounds"][0] + layout["bubble_bounds"][2]) / 2, layout["bubble_bounds"][3])
    assert math.dist(bubble_center, layout["tail_tip"]) <= image.height * 0.16 + 1


def test_missing_safe_zone_falls_back_to_non_overlapping_pair() -> None:
    renderer = load_renderer()
    zones = renderer.resolve_dialogue_zones(
        [{"x": 0.62, "y": 0.05, "width": 0.33, "height": 0.25}],
        2,
    )
    assert len(zones) == 2
    first_right = zones[0]["x"] + zones[0]["width"]
    assert first_right < zones[1]["x"]


def test_compose_page_keeps_four_equal_cells(tmp_path) -> None:
    renderer = load_renderer()
    sources = []
    for index in range(4):
        source = tmp_path / f"{index}.png"
        Image.new("RGB", (1664, 928), (index * 30, 60, 90)).save(source)
        sources.append(source)
    destination = tmp_path / "page.png"
    renderer.compose_page(sources, destination)
    assert Image.open(destination).size[0] > 1664 * 2
    assert Image.open(destination).size[1] > 928 * 2
