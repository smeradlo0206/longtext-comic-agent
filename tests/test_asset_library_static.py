"""Static isolation checks for the asset intake command and review route."""

from pathlib import Path


def test_asset_library_is_anime_only_no_scrape_and_ignores_runtime_assets() -> None:
    source = Path("comic_agent/services/asset_library.py").read_text(encoding="utf-8")
    script = Path("scripts/asset_intake.py").read_text(encoding="utf-8")
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert "REFERENCE_ONLY_CATALOG" in source
    assert "no automatic image-download source" in source
    assert "style:manga_line_art" in source
    assert "POSEMANIACS" not in source
    assert "browser" not in source.lower()
    assert "asset_library/*" in ignored
    assert "discover" in script and "download" in script and "report" in script
