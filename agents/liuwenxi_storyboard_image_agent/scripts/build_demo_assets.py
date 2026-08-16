from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "assets" / "presets" / "demo-v1"
SCALE = 3


def p(value: int) -> int:
    return value * SCALE


def points(values: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(p(x), p(y)) for x, y in values]


def canvas(size: tuple[int, int], color: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (p(size[0]), p(size[1])), color)
    return image, ImageDraw.Draw(image)


def line(draw: ImageDraw.ImageDraw, values, fill: str, width: int = 3) -> None:
    draw.line(points(values), fill=fill, width=p(width), joint="curve")


def polygon(draw: ImageDraw.ImageDraw, values, fill: str, outline: str | None = None, width: int = 2) -> None:
    draw.polygon(points(values), fill=fill)
    if outline:
        draw.line(points(values + [values[0]]), fill=outline, width=p(width), joint="curve")


def ellipse(draw: ImageDraw.ImageDraw, box, fill: str, outline: str | None = None, width: int = 2) -> None:
    draw.ellipse(tuple(p(v) for v in box), fill=fill, outline=outline, width=p(width))


def rectangle(draw: ImageDraw.ImageDraw, box, fill: str, outline: str | None = None, width: int = 2) -> None:
    draw.rectangle(tuple(p(v) for v in box), fill=fill, outline=outline, width=p(width))


def save(image: Image.Image, relative: str) -> Path:
    path = PROFILE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((image.width // SCALE, image.height // SCALE), Image.Resampling.LANCZOS).save(
        path, format="PNG", optimize=True
    )
    return path


def character_reference() -> Path:
    image, draw = canvas((1024, 1024), "#e9e4d8")
    rectangle(draw, (45, 45, 979, 979), "#f4f1e8", "#26373a", 4)
    # Quiet reference-board dividers and palette swatches.
    line(draw, [(680, 80), (680, 944)], "#b5b0a5", 2)
    for index, color in enumerate(("#173d43", "#2d666a", "#b8d3c8", "#d7b36d", "#2b2525")):
        rectangle(draw, (730 + index * 45, 875, 762 + index * 45, 907), color, "#26373a", 1)

    # Full-body front view.
    ellipse(draw, (285, 105, 465, 285), "#e8c8ae", "#272326", 4)
    polygon(draw, [(290, 145), (315, 82), (430, 88), (470, 150), (445, 122), (430, 265), (325, 270), (300, 185)], "#242426", "#242426", 3)
    polygon(draw, [(348, 78), (383, 38), (418, 80), (400, 135), (360, 130)], "#242426", "#242426", 3)
    line(draw, [(339, 182), (360, 175)], "#3f3030", 3)
    line(draw, [(398, 175), (420, 182)], "#3f3030", 3)
    line(draw, [(377, 210), (395, 211)], "#a56560", 2)
    polygon(draw, [(317, 280), (438, 280), (500, 470), (475, 760), (285, 760), (255, 470)], "#24555c", "#1e3034", 4)
    polygon(draw, [(317, 280), (378, 365), (438, 280), (415, 470), (340, 470)], "#d8e8df", "#1e3034", 3)
    polygon(draw, [(255, 335), (195, 530), (248, 548), (330, 390)], "#2e6c70", "#1e3034", 4)
    polygon(draw, [(438, 335), (552, 520), (505, 555), (420, 400)], "#2e6c70", "#1e3034", 4)
    ellipse(draw, (183, 510, 244, 570), "#e8c8ae", "#272326", 3)
    ellipse(draw, (500, 520, 558, 580), "#e8c8ae", "#272326", 3)
    rectangle(draw, (282, 455, 480, 495), "#c3a25e", "#1e3034", 3)
    ellipse(draw, (366, 458, 402, 493), "#83b6a1", "#1e3034", 2)
    polygon(draw, [(286, 750), (475, 750), (530, 895), (403, 920), (375, 790), (350, 920), (230, 895)], "#173d43", "#1e3034", 4)
    polygon(draw, [(285, 760), (350, 760), (320, 934), (238, 934)], "#f0eee8", "#1e3034", 3)
    polygon(draw, [(407, 760), (475, 760), (520, 934), (435, 934)], "#f0eee8", "#1e3034", 3)

    # Face close-up inset with hair and expression details.
    ellipse(draw, (730, 155, 930, 355), "#e8c8ae", "#26373a", 4)
    polygon(draw, [(725, 215), (748, 142), (848, 112), (930, 170), (946, 248), (910, 212), (897, 330), (760, 330), (744, 250)], "#242426", "#242426", 3)
    line(draw, [(770, 240), (805, 230)], "#3f3030", 4)
    line(draw, [(857, 230), (892, 240)], "#3f3030", 4)
    ellipse(draw, (784, 238, 803, 254), "#273b3b", None)
    ellipse(draw, (862, 238, 881, 254), "#273b3b", None)
    line(draw, [(813, 294), (850, 297)], "#a56560", 3)
    polygon(draw, [(752, 360), (910, 360), (947, 580), (710, 580)], "#24555c", "#26373a", 4)
    polygon(draw, [(752, 360), (830, 450), (910, 360), (875, 525), (785, 525)], "#d8e8df", "#26373a", 3)

    # Side silhouette inset.
    ellipse(draw, (760, 650, 900, 790), "#e8c8ae", "#26373a", 3)
    polygon(draw, [(760, 685), (790, 620), (875, 640), (916, 700), (876, 680), (865, 785), (785, 790)], "#242426", "#242426", 3)
    line(draw, [(875, 710), (898, 714)], "#3f3030", 3)
    return save(image, "characters/char-a-ref-01.png")


def scene_reference() -> Path:
    image, draw = canvas((1536, 1024), "#17262c")
    # Ceiling, back wall and perspective floor.
    polygon(draw, [(0, 0), (1536, 0), (1320, 250), (210, 250)], "#20353b")
    polygon(draw, [(0, 1024), (1536, 1024), (1220, 650), (315, 650)], "#513d32")
    rectangle(draw, (180, 190, 1355, 680), "#39464a", "#121d21", 6)
    # Moonlit lattice window.
    rectangle(draw, (630, 220, 905, 505), "#9bb9b5", "#18282d", 12)
    for x in (690, 750, 810, 870):
        line(draw, [(x, 225), (x, 500)], "#294348", 6)
    for y in (285, 350, 415):
        line(draw, [(635, y), (900, y)], "#294348", 6)
    ellipse(draw, (700, 260, 840, 400), "#d7d7b5")
    # Tall bookcases on both sides.
    for x0, x1 in ((205, 570), (965, 1330)):
        rectangle(draw, (x0, 220, x1, 700), "#3b2924", "#171514", 8)
        for y in (330, 445, 560, 675):
            rectangle(draw, (x0 + 15, y, x1 - 15, y + 12), "#9b7045", "#211915", 2)
        for shelf in range(4):
            y = 245 + shelf * 115
            cursor = x0 + 25
            colors = ("#6e3f34", "#31545a", "#7f6741", "#496146", "#744e5c")
            for book in range(9):
                width = 23 + (book * 7 + shelf * 5) % 18
                height = 62 + (book * 13) % 30
                rectangle(draw, (cursor, y + 74 - height, cursor + width, y + 78), colors[book % len(colors)], "#201b19", 2)
                cursor += width + 5
    # Central desk with open drawer and letter-shaped empty space.
    polygon(draw, [(510, 605), (1028, 605), (1130, 765), (410, 765)], "#78523a", "#211713", 7)
    rectangle(draw, (505, 755, 1035, 925), "#563b2d", "#211713", 7)
    rectangle(draw, (585, 775, 760, 845), "#30231f", "#b08b56", 5)
    polygon(draw, [(585, 842), (760, 842), (795, 895), (545, 895)], "#422e25", "#211713", 5)
    rectangle(draw, (800, 665, 950, 716), "#d5c7a4", "#32261e", 3)
    line(draw, [(820, 682), (920, 682)], "#8b7458", 2)
    line(draw, [(820, 698), (900, 698)], "#8b7458", 2)
    # Candles and warm pools of light.
    for x in (460, 1060):
        rectangle(draw, (x, 570, x + 22, 650), "#d7c28f", "#2a211b", 3)
        polygon(draw, [(x + 11, 560), (x + 1, 585), (x + 11, 578), (x + 21, 585)], "#f1b44c", "#7d4d20", 2)
    # Foreground pillars and depth lines.
    polygon(draw, [(0, 0), (125, 0), (190, 1024), (0, 1024)], "#251c1a", "#111", 6)
    polygon(draw, [(1410, 0), (1536, 0), (1536, 1024), (1345, 1024)], "#251c1a", "#111", 6)
    line(draw, [(210, 250), (410, 1024)], "#9b7045", 5)
    line(draw, [(1320, 250), (1130, 1024)], "#9b7045", 5)
    return save(image, "scenes/scene-library-ref-01.png")


def style_reference() -> Path:
    image, draw = canvas((1024, 1024), "#f2efe6")
    rectangle(draw, (40, 40, 984, 984), "#e8e5da", "#1f3034", 6)
    # Dynamic diagonal comic composition with restrained teal/gold/red palette.
    polygon(draw, [(42, 640), (640, 42), (982, 42), (982, 300), (300, 982), (42, 982)], "#173f45")
    polygon(draw, [(42, 740), (740, 42), (900, 42), (200, 850)], "#d3a95d")
    polygon(draw, [(115, 835), (785, 165), (930, 310), (270, 970)], "#ecede7", "#1f3034", 8)
    # Ink-like mountain and cloud silhouettes.
    polygon(draw, [(80, 600), (245, 390), (365, 545), (490, 360), (650, 590)], "#496468", "#1f3034", 7)
    polygon(draw, [(390, 620), (555, 440), (680, 565), (805, 405), (950, 640)], "#2c4d53", "#1f3034", 7)
    for y, offset in ((650, 0), (700, 60), (755, -20)):
        line(draw, [(90 + offset, y), (290 + offset, y - 25), (480 + offset, y + 5), (720 + offset, y - 30), (940, y)], "#f4f1e8", 18)
    # Foreground figure silhouette demonstrates crisp anime linework, not identity.
    ellipse(draw, (365, 350, 515, 500), "#dfbfa4", "#20272a", 6)
    polygon(draw, [(360, 390), (390, 320), (485, 330), (525, 405), (500, 380), (475, 490), (390, 490)], "#222426", "#222426", 4)
    polygon(draw, [(330, 500), (540, 500), (650, 875), (210, 875)], "#284f56", "#20272a", 8)
    polygon(draw, [(330, 500), (435, 625), (540, 500), (505, 690), (365, 690)], "#dce8df", "#20272a", 5)
    line(draw, [(385, 420), (415, 412)], "#303536", 4)
    line(draw, [(454, 412), (484, 420)], "#303536", 4)
    # Speed-line accents and red focal mark.
    for delta in range(0, 180, 30):
        line(draw, [(650 + delta, 200), (880 + delta // 2, 80)], "#20373b", 4)
    ellipse(draw, (770, 700, 870, 800), "#9c4037", "#4a2724", 5)
    return save(image, "styles/style-comic-ref-01.png")


def update_manifest(paths: list[Path]) -> None:
    manifest_path = PROFILE / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_path = {str(path.relative_to(PROFILE)).replace("\\", "/"): path for path in paths}
    for asset in payload["assets"]:
        path = by_path[asset["relative_path"]]
        asset["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    paths = [character_reference(), scene_reference(), style_reference()]
    update_manifest(paths)
    for path in paths:
        print(f"{path.relative_to(ROOT)} {hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
