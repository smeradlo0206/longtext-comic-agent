from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT = Path("C:/Windows/Fonts/Noto Sans SC Medium (TrueType).otf")
PLACEMENT_X = {"left": 0.25, "center": 0.5, "right": 0.75, "background": 0.5}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def zone_pixels(zone: dict, width: int, height: int) -> tuple[int, int, int, int]:
    return (
        round(zone["x"] * width),
        round(zone["y"] * height),
        round((zone["x"] + zone["width"]) * width),
        round((zone["y"] + zone["height"]) * height),
    )


def fallback_zone(index: int, total: int) -> dict:
    width = 0.36 if total > 1 else 0.42
    x = 0.04 if index % 2 == 0 else 1.0 - width - 0.04
    y = 0.04 + (index // 2) * 0.24
    return {"x": x, "y": y, "width": width, "height": 0.20}


def resolve_dialogue_zones(zones: list[dict], total: int) -> list[dict]:
    if len(zones) >= total:
        return zones[:total]
    return [fallback_zone(index, total) for index in range(total)]


def speaker_target(plan: dict, speaker_id: str, width: int, height: int) -> tuple[int, int]:
    character = next((item for item in plan.get("characters", []) if item["character_id"] == speaker_id), None)
    x = PLACEMENT_X.get(character.get("placement") if character else "center", 0.5)
    return round(x * width), round(0.58 * height)


def render_bubble(
    image: Image.Image,
    text: str,
    zone: dict,
    target: tuple[int, int],
    font_path: Path,
) -> dict:
    draw = ImageDraw.Draw(image)
    x1, y1, x2, y2 = zone_pixels(zone, image.width, image.height)
    x1, y1 = max(12, x1), max(12, y1)
    x2, y2 = min(image.width - 12, x2), min(image.height - 12, y2)
    padding = max(12, round(image.width * 0.012))
    available_width = max(80, x2 - x1 - padding * 2)
    font_size = max(24, round(image.height * 0.040))
    while font_size >= 18:
        font = ImageFont.truetype(str(font_path), font_size)
        lines = wrap_text(draw, text, font, available_width)
        line_height = math.ceil(font_size * 1.35)
        required_height = len(lines) * line_height + padding * 2
        if required_height <= y2 - y1:
            break
        font_size -= 2
    bubble_width = min(x2 - x1, max(draw.textbbox((0, 0), line, font=font)[2] for line in lines) + padding * 2)
    bubble_height = min(y2 - y1, len(lines) * line_height + padding * 2)
    bx1 = x1 + (x2 - x1 - bubble_width) // 2
    by1 = y1 + (y2 - y1 - bubble_height) // 2
    bx2, by2 = bx1 + bubble_width, by1 + bubble_height
    center_x = (bx1 + bx2) // 2
    tail_base_y = by2 - 2
    tail_half = max(10, round(image.width * 0.008))
    delta_x = target[0] - center_x
    delta_y = max(18, target[1] - tail_base_y)
    distance = math.hypot(delta_x, delta_y)
    max_tail_length = max(64, round(image.height * 0.16))
    scale = min(1.0, max_tail_length / distance)
    tail_tip = (
        round(center_x + delta_x * scale),
        min(round(tail_base_y + delta_y * scale), image.height - 8),
    )
    draw.polygon(
        [(center_x - tail_half, tail_base_y), (center_x + tail_half, tail_base_y), tail_tip],
        fill="white",
        outline="black",
    )
    radius = max(18, round(bubble_height * 0.23))
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=radius, fill="white", outline="black", width=max(2, image.width // 600))
    text_y = by1 + padding
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        text_x = bx1 + (bubble_width - (box[2] - box[0])) // 2
        draw.text((text_x, text_y), line, fill="black", font=font)
        text_y += line_height
    return {
        "zone": zone,
        "bubble_bounds": [bx1, by1, bx2, by2],
        "font_size": font_size,
        "lines": lines,
        "target": list(target),
        "tail_tip": list(tail_tip),
    }


def compose_page(panel_paths: list[Path], destination: Path) -> None:
    panels = [Image.open(path).convert("RGB") for path in panel_paths]
    cell_width = max(item.width for item in panels)
    cell_height = max(item.height for item in panels)
    gutter = max(24, cell_width // 45)
    page = Image.new("RGB", (cell_width * 2 + gutter * 3, cell_height * 2 + gutter * 3), "white")
    for index, panel in enumerate(panels):
        panel.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
        column, row = index % 2, index // 2
        x = gutter + column * (cell_width + gutter) + (cell_width - panel.width) // 2
        y = gutter + row * (cell_height + gutter) + (cell_height - panel.height) // 2
        page.paste(panel, (x, y))
    destination.parent.mkdir(parents=True, exist_ok=True)
    page.save(destination, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render deterministic editable Chinese dialogue bubbles from SceneJob and VisualPlan")
    parser.add_argument("--scene-job", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    args = parser.parse_args()
    job = load_json(args.scene_job)
    result = load_json(args.result)
    plans = {item["panel_id"]: item["visual_plan"] for item in result["panels"]}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rendered_paths = []
    layout = []
    for panel in sorted(job["panels"], key=lambda item: item["sequence_no"]):
        panel_id = panel["panel_id"]
        raw_path = args.raw_dir / f"{panel_id}.png"
        image = Image.open(raw_path).convert("RGB")
        plan = plans[panel_id]
        zones = resolve_dialogue_zones(plan.get("dialogue_safe_zones", []), len(panel.get("dialogue", [])))
        bubble_layout = []
        for index, dialogue in enumerate(panel.get("dialogue", [])):
            zone = zones[index]
            bubble_layout.append(
                {
                    "speaker_id": dialogue["speaker_id"],
                    "text": dialogue["text"],
                    **render_bubble(
                        image,
                        dialogue["text"],
                        zone,
                        speaker_target(plan, dialogue["speaker_id"], image.width, image.height),
                        args.font,
                    ),
                }
            )
        destination = output / f"{panel_id}-dialogue.png"
        image.save(destination, format="PNG", optimize=True)
        rendered_paths.append(destination)
        layout.append({"panel_id": panel_id, "source": str(raw_path), "output": str(destination), "bubbles": bubble_layout})
    compose_page(rendered_paths, output / "comic-page-2x2.png")
    (output / "dialogue-layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"panels": [str(path) for path in rendered_paths], "page": str(output / "comic-page-2x2.png")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
