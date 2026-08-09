from pathlib import Path


def test_web_console_static_html_exposes_demo_controls_without_local_secrets() -> None:
    html_path = Path("web_console/index.html")

    html = html_path.read_text(encoding="utf-8")

    assert 'id="accessCode"' in html
    assert 'id="verifyAccess"' in html
    assert "Access Not Required" in html
    assert 'id="runMock"' in html
    assert 'id="runRealEvent"' in html
    assert "Real Event Agent · event only" in html
    assert 'id="narrativeMode"' in html
    assert 'id="narrativeChunkIds"' in html
    assert 'id="narrativeChunkLimit"' in html
    assert 'id="narrativeChunkOffset"' in html
    assert 'id="narrativeMaxChars"' in html
    assert 'id="narrativeRealLlmRequested"' in html
    assert 'id="runNarrativeAnalyst"' in html
    assert 'id="narrativeSummary"' in html
    assert 'id="narrativeProposal"' in html
    assert 'id="narrativeProposalList"' in html
    assert 'id="narrativeEvidenceStatus"' in html
    assert 'id="narrativeProviderDiagnostics"' in html
    assert 'id="manualReviewChecklist"' in html
    assert 'id="narrativeSelectedChunks"' in html
    assert "Selected input chunks" in html
    assert "本次输入 chunks" in html
    assert "event_extraction" in html
    assert "event_extraction · EventProposalBatchV1" in html
    assert "entity_extraction · EntityProposalBatchV1" in html
    assert "claim_extraction · ClaimProposalBatchV1" in html
    assert "Proposal List" in html
    assert "renderProposalList" in html
    assert "proposalItems" in html
    assert "event_evidence_results" in html
    assert "entity_evidence_results" in html
    assert "creature_subtype" in html
    assert "claim_evidence_results" in html
    assert "temporal_scope" in html
    assert "events_cover_major_plot_points" in html
    assert "entities_cover_major_entities" in html
    assert "creature_classification_correct" in html
    assert "creature_subtype_supported_or_null" in html
    assert "claims_cover_major_claims" in html
    assert "event_count_reasonable" in html
    assert "no_duplicate_events" in html
    assert "no_duplicate_entities" in html
    assert "no_duplicate_claims" in html
    assert "claim_is_attributable_proposition" in html
    assert "claim_type_matches_decision_table" in html
    assert "factual_assertions_are_unhedged" in html
    assert "belief_and_hypothesis_distinguished" in html
    assert "evaluation_and_interpretation_distinguished" in html
    assert "claim_temporal_scope_correct" in html
    assert "prediction_commitment_distinguished" in html
    assert "no_duplicate_or_invented_claims" in html
    assert "no_invented_events" in html
    assert "every_event_has_supporting_evidence" in html
    assert "every_entity_has_supporting_evidence" in html
    assert "every_claim_has_supporting_evidence" in html
    assert "event_summaries_supported_by_quotes" in html
    assert "entity_extraction" in html
    assert "claim_extraction" in html
    assert "/agent-runs/narrative-analyst" in html
    assert "clearSelectedChunks" in html
    assert "clearSelectedChunks();" in html
    assert "请先选择 1-3 个 chunks，避免误用旧项目文本。" in html
    assert "body.chunk_ids = chunkIds;" in html
    assert 'const requestedMode = $("narrativeMode").value;' in html
    assert "assertNarrativeModeMatches" in html
    assert "Narrative Analyst mode mismatch" in html
    assert "expectedSchemaForMode" in html
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


def test_web_console_does_not_default_to_demo_project_after_refresh() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="projectId" value="demo-project"' not in html
    assert 'id="apiBase" value="http://127.0.0.1:8080"' in html
    assert "initializeProjectId" in html
    assert "localStorage" in html
    assert "comic-agent-project-id" in html


def test_web_console_can_restore_narrative_proposal_from_agent_run_detail() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert "renderNarrativeResultFromRunDetail" in html
    assert 'data.agent_name.startsWith("narrative-analyst:")' in html
    assert "data.proposal ?? data.provider_result?.structured_output ?? null" in html


def test_web_console_keeps_wide_proposal_tables_inside_their_own_scroll_area() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert ".app, main, .grid, .stack, section, .body { min-width: 0; }" in html
    assert ".table-scroll {" in html
    assert "overflow-x: scroll;" in html
    assert '<div class="table-scroll"><table>' in html
    assert ".table-scroll-toolbar" in html
    assert 'data-table-scroll="left"' in html
    assert 'data-table-scroll="right"' in html
    assert "scrollBy" in html
    assert ".full-span { grid-column: 1 / -1; }" in html
    assert ".full-span { order: 1; }" in html
    assert 'id="narrative" class="full-span"' in html


def test_web_console_gives_window_execution_details_a_dedicated_scroll_viewport() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert "window-execution-shell" in html
    assert "window-execution-toolbar" in html
    assert "window-execution-viewport" in html
    assert "window-execution-table" in html
    assert "#narrative { overflow: visible; }" in html
    assert ".window-execution-viewport" in html
    assert "overflow-x: auto;" in html
    assert "overflow-y: hidden;" in html
    assert "touch-action: pan-x;" in html
    assert "scrollbar-gutter: stable;" in html
    assert "min-width: 1400px;" in html
    assert 'data-window-scroll="left"' in html
    assert 'data-window-scroll="right"' in html
    assert "windowExecutionViewport.scrollBy" in html


def test_web_console_manual_review_empty_values_are_explained_in_chinese() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert "待人工填写" in html
    assert '? "manual"' not in html


def test_web_console_exposes_whole_document_analysis_as_the_normal_flow() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert '<input id="apiBase" value="http://127.0.0.1:8080" />' in html
    assert 'id="analysisDocumentId"' in html
    assert 'id="loadAnalysisDocuments"' in html
    assert 'data-analysis-mode="event_extraction"' in html
    assert 'data-analysis-mode="entity_extraction"' in html
    assert 'data-analysis-mode="claim_extraction"' in html
    assert 'id="analysisRealLlmRequested"' in html
    assert 'id="startWholeDocumentAnalysis"' in html
    assert 'id="wholeDocumentProgress"' in html
    assert 'id="wholeDocumentProposalList"' in html
    assert 'id="resumeWholeDocumentAnalysis"' in html
    assert 'id="advancedNarrativeDebug"' in html
    assert "startWholeDocumentAnalysis" in html
    assert "loadWholeDocumentProgress" in html
    assert "renderWholeDocumentResult" in html
    assert "Window execution details" in html
    assert 'id="wholeDocumentWindows"' in html
    assert "loadWholeDocumentWindows" in html
    assert "ensureWholeDocumentRealLlmEnabled" in html
    assert 'request("/settings/llm/status")' in html
    assert '"attempts"' in html
    assert '"input budget"' in html
    assert '"previous failure"' in html
    assert '"safe diagnostics"' in html
    assert "/narrative-analysis-runs/" in html
    assert "/documents/${encodeURIComponent(documentId)}/narrative-analysis-runs" in html
    advanced_start = html.index('id="advancedNarrativeDebug"')
    manual_chunk_input = html.index('id="narrativeChunkIds"')
    advanced_end = html.index("</details>", advanced_start)
    assert advanced_start < manual_chunk_input < advanced_end


def test_web_console_exposes_whole_document_outputs_for_manual_review() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="wholeDocumentSummary"' in html
    assert 'id="wholeDocumentFullProposal"' in html
    assert 'id="wholeDocumentProposalDetail"' in html
    assert "renderWholeDocumentSummary" in html
    assert "renderWholeDocumentProposalDetail" in html
    assert "data-whole-proposal-mode" in html
    assert "scheduleWholeDocumentProgressPoll" in html
