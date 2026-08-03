from pathlib import Path


def test_web_console_static_html_exposes_demo_controls_without_local_secrets() -> None:
    html_path = Path("web_console/index.html")

    html = html_path.read_text(encoding="utf-8")

    assert 'id="accessCode"' in html
    assert 'id="verifyAccess"' in html
    assert "Access Not Required" in html
    assert 'id="runMock"' in html
    assert 'id="runRealEvent"' in html
    assert 'id="narrativeMode"' in html
    assert 'id="narrativeChunkIds"' in html
    assert 'id="narrativeChunkLimit"' in html
    assert 'id="narrativeChunkOffset"' in html
    assert 'id="narrativeMaxChars"' in html
    assert 'id="narrativeRealLlmRequested"' in html
    assert 'id="runNarrativeAnalyst"' in html
    assert 'id="narrativeSummary"' in html
    assert 'id="narrativeProposal"' in html
    assert 'id="narrativeEvidenceStatus"' in html
    assert 'id="narrativeProviderDiagnostics"' in html
    assert 'id="manualReviewChecklist"' in html
    assert 'id="narrativeSelectedChunks"' in html
    assert "Selected input chunks" in html
    assert "本次输入 chunks" in html
    assert "event_extraction" in html
    assert "entity_extraction" in html
    assert "claim_extraction" in html
    assert "/agent-runs/narrative-analyst" in html
    assert "clearSelectedChunks" in html
    assert "clearSelectedChunks();" in html
    assert "请先选择 1-3 个 chunks，避免误用旧项目文本。" in html
    assert "body.chunk_ids = chunkIds;" in html
    assert 'addEventListener("input", () => renderNarrativeSelectedChunks())' in html
    assert "X-Demo-Access-Code" in html
    assert "local_eval" not in html
    assert "output/" not in html
    assert "LLM_API_KEY" not in html
    assert "OPENAI_API_KEY" not in html
    assert "replace-with" not in html
    assert "pretty(chunk)" not in html
    assert "highlightQuote(chunk.text" not in html
    assert "sanitizeRunDetail" in html
    assert "sanitizeNarrativeResponse" in html
    assert "renderManualReviewChecklist" in html
    assert "sanitizedChunkDetail" in html
    assert "evidenceSnippet" in html
    assert "raw_output" in html
