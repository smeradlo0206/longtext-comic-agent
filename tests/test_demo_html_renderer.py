from pathlib import Path

from comic_agent.demo.html_renderer import DemoHtmlRenderer
from comic_agent.demo.pipeline import ComicDemoPipeline


def _artifact(tmp_path: Path) -> Path:
    source = tmp_path / "林岚-demo.txt"
    source.write_text("Lin meets Mira at the gate.", encoding="utf-8")
    return (
        ComicDemoPipeline()
        .run(
            input_path=source,
            output_root=tmp_path / "artifacts",
            provider_mode="deterministic",
            skip_storybible_provider=True,
        )
        .artifact_dir
    )


def test_renderer_creates_single_offline_html_with_core_sections(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    output = DemoHtmlRenderer().render(artifact)
    page = output.read_text(encoding="utf-8")
    assert output.is_file()
    for text in ("LongText", "Characters", "Timeline", "Scenes &amp; Panels", "PANEL"):
        assert text in page
    assert "DEMO_DETERMINISTIC" in page
    assert "DEMO_FALLBACK" in page
    assert "Lin" in page and "Mira" in page


def test_runner_generates_html_and_does_not_leak_secrets_or_absolute_input(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    page = (artifact / "demo.html").read_text(encoding="utf-8")
    assert "林岚-demo.txt" in page
    assert str(tmp_path) not in page
    for forbidden in ("Authorization", "Bearer", "LLM_API_KEY"):
        assert forbidden not in page
