from pathlib import Path

from PIL import Image, ImageChops

from comic_agent.schemas.comic_production import DialogueLayoutSettingsV1
from comic_agent.schemas.visual import PanelTextOverlayV1
from comic_agent.services.comic_letterer import ComicLetterer


def test_letterer_preserves_base_panel_and_writes_overlay_copy(tmp_path: Path) -> None:
    source = tmp_path / "panel.png"
    destination = tmp_path / "lettered-panel.png"
    Image.new("RGB", (640, 360), (40, 100, 160)).save(source)
    before = source.read_bytes()
    overlay = PanelTextOverlayV1(
        overlay_id="overlay-1",
        kind="dialogue",
        text="Tea is ready.",
        speaker_entity_id="character.lead",
        source_quote_start=1,
        source_quote_end=14,
        preferred_region="top_left",
    )

    artifact = ComicLetterer().render(
        source=source,
        destination=destination,
        overlays=[overlay],
        settings=DialogueLayoutSettingsV1(enabled=True),
    )

    assert source.read_bytes() == before
    assert artifact["overlay_count"] == 1
    with Image.open(source) as base, Image.open(destination) as lettered:
        assert ImageChops.difference(base, lettered).getbbox() is not None
