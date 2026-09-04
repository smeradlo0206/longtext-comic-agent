"""Deterministic dialogue and caption layout for generated comic panels."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from comic_agent.schemas.comic_production import DialogueLayoutSettingsV1
from comic_agent.schemas.visual import PanelTextOverlayV1

DEFAULT_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
)


def _font_path(settings: DialogueLayoutSettingsV1, text: str) -> Path | None:
    if settings.font_path is not None and not Path(settings.font_path).expanduser().is_file():
        raise FileNotFoundError(f"lettering font does not exist: {settings.font_path}")
    candidates = (
        (Path(settings.font_path).expanduser(),)
        if settings.font_path is not None
        else DEFAULT_FONT_CANDIDATES
    )
    path = next((item.resolve() for item in candidates if item.is_file()), None)
    return path


def _load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.truetype(str(path), size=size) if path else ImageFont.load_default(size=size)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: int,
) -> str:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


class ComicLetterer:
    """Render source-grounded text without modifying the generated base panel."""

    renderer_id = "pil-comic-letterer-v1"

    def render(
        self,
        *,
        source: Path,
        destination: Path,
        overlays: list[PanelTextOverlayV1],
        settings: DialogueLayoutSettingsV1,
    ) -> dict[str, object]:
        if not settings.enabled or not overlays:
            shutil.copy2(source, destination)
            destination.chmod(0o600)
            with Image.open(destination) as copied:
                return {
                    "file": destination.name,
                    "width": copied.width,
                    "height": copied.height,
                    "overlay_count": 0,
                    "renderer": self.renderer_id,
                }

        all_text = "".join(item.text for item in overlays)
        font_path = _font_path(settings, all_text)
        with Image.open(source) as loaded:
            image = loaded.convert("RGB")
        try:
            draw = ImageDraw.Draw(image)
            width, height = image.size
            margin = max(12, round(min(width, height) * 0.025))
            max_bubble_width = round(width * settings.max_bubble_width_ratio)
            region_offsets: dict[str, float] = {}
            rendered: list[dict[str, object]] = []
            for overlay in overlays:
                font_size = min(
                    settings.max_font_size,
                    max(settings.min_font_size, round(height * 0.045)),
                )
                font = _load_font(font_path, font_size)
                inner_width = max_bubble_width - settings.bubble_padding * 2
                wrapped = _wrap_text(draw, overlay.text, font, inner_width)
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=4)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                bubble_width = text_width + settings.bubble_padding * 2
                bubble_height = text_height + settings.bubble_padding * 2
                region = overlay.preferred_region
                offset = region_offsets.get(region, 0)
                left = margin if region.endswith("left") else width - margin - bubble_width
                top = (
                    margin + offset
                    if region.startswith("top")
                    else height - margin - bubble_height - offset
                )
                left = max(0, min(left, width - bubble_width))
                top = max(0, min(top, height - bubble_height))
                right = left + bubble_width
                bottom = top + bubble_height
                tail_x = left + bubble_width * (0.72 if region.endswith("left") else 0.28)
                if overlay.kind == "dialogue":
                    tail_y = bottom + min(margin, height - bottom)
                    draw.polygon(
                        [
                            (tail_x - 10, bottom - 3),
                            (tail_x + 12, bottom - 3),
                            (tail_x, tail_y),
                        ],
                        fill="white",
                        outline="black",
                    )
                    draw.rounded_rectangle(
                        (left, top, right, bottom),
                        radius=max(8, settings.bubble_padding),
                        fill="white",
                        outline="black",
                        width=max(2, round(width / 500)),
                    )
                else:
                    draw.rectangle(
                        (left, top, right, bottom),
                        fill=(255, 250, 224),
                        outline="black",
                        width=max(2, round(width / 500)),
                    )
                draw.multiline_text(
                    (left + settings.bubble_padding, top + settings.bubble_padding - bbox[1]),
                    wrapped,
                    font=font,
                    fill="black",
                    spacing=4,
                )
                region_offsets[region] = offset + bubble_height + margin
                rendered.append(
                    {
                        "overlay_id": overlay.overlay_id,
                        "kind": overlay.kind,
                        "speaker_entity_id": overlay.speaker_entity_id,
                        "region": region,
                        "box": [left, top, right, bottom],
                    }
                )
            image.save(destination, format="PNG", optimize=True)
            destination.chmod(0o600)
            return {
                "file": destination.name,
                "width": width,
                "height": height,
                "overlay_count": len(rendered),
                "overlays": rendered,
                "renderer": self.renderer_id,
                "font": str(font_path) if font_path else "Pillow default",
            }
        finally:
            image.close()
