from pathlib import Path


def test_web_console_static_html_exposes_demo_controls_without_local_secrets() -> None:
    html_path = Path("web_console/index.html")

    html = html_path.read_text(encoding="utf-8")

    assert 'id="accessCode"' in html
    assert 'id="verifyAccess"' in html
    assert 'id="runMock"' in html
    assert 'id="runRealEvent"' in html
    assert "X-Demo-Access-Code" in html
    assert "local_eval" not in html
    assert "output/" not in html
    assert "LLM_API_KEY" not in html
    assert "OPENAI_API_KEY" not in html
    assert "replace-with" not in html
    assert "pretty(chunk)" not in html
    assert "highlightQuote(chunk.text" not in html
    assert "sanitizeRunDetail" in html
    assert "sanitizedChunkDetail" in html
    assert "evidenceSnippet" in html
