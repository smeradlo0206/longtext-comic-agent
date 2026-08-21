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
    assert 'body.append("narrative_modes", JSON.stringify([' in html
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
    assert "knowledge_state_extraction · KnowledgeStateProposalBatchV1" in html
    assert "state_change_extraction · StateChangeProposalBatchV1" in html
    assert "relationship_signal_extraction · RelationshipSignalProposalBatchV1" in html
    assert "Proposal List" in html
    assert "renderProposalList" in html
    assert "proposalItems" in html
    assert "event_evidence_results" in html
    assert "entity_evidence_results" in html
    assert "creature_subtype" in html
    assert "claim_evidence_results" in html
    assert "knowledge_state_evidence_results" in html
    assert "knowledge_state_proposals_count" in html
    assert "proposal.target?.target_text" in html
    assert "subject_target_and_anchor_resolution_preserved" in html
    assert "renderKnowledgeStateProposalList" in html
    assert "renderStateChangeProposalList" in html
    assert "buildStateChangePossibleDuplicateReview" in html
    assert "可能重复：事件表达不同" in html
    assert "仅供人工审核；未自动合并" in html
    assert "stateChangePossibleDuplicateMarkup" in html
    assert "result.state_changes" in html
    assert "Attribute path" in html
    assert "Old value" in html
    assert "New value" in html
    assert "Persistent" in html
    assert "未发现可审计状态变化" in html
    assert "Relationship Signal audit" in html
    assert "未发现可审计关系信号" in html
    assert "Relationship domain" in html
    assert "Relationship kind" in html
    assert "Directionality" in html
    assert "Source speaker" in html
    assert "Temporal anchor" in html
    assert "result.relationship_signals" in html
    assert "Proposal ID" in html
    assert "Batch / Agent Run" in html
    assert "Status" in html
    assert "Basis" in html
    assert "Subject resolution" in html
    assert "Target kind" in html
    assert "Target resolution" in html
    assert "Valid from" in html
    assert "Valid until" in html
    assert "Evidence status" in html
    assert "未声明" in html
    assert "未解析：" in html
    assert "data-evidence-run" in html
    assert '"resolution / temporal"' not in html
    assert "expandableTargetSummary" in html
    assert "查看完整" in html
    assert "target-summary" in html
    assert "可能重复：目标类型不一致" in html
    assert "可能重复：目标表达不同" in html
    assert "buildKnowledgePossibleDuplicateReview" in html
    assert "normalizeKnowledgeDuplicateTarget" in html
    assert "data-evidence-run" in html
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
    assert 'id="advancedNarrativeDebug" open' in html
    assert (
        '$("runNarrativeAnalyst").disabled = !state.accessGranted '
        '|| state.selectedChunks.size < 1;'
    ) in html
    assert "sidebar-nav-shell" in html
    assert "data-sidebar-scroll" in html
    assert "Scroll navigation left" in html
    assert "Scroll navigation right" in html


def test_web_console_does_not_default_to_demo_project_after_refresh() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="projectId" value="demo-project"' not in html
    assert 'id="apiBase" value="" placeholder="Same origin"' in html
    assert "window.location.origin" in html
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

    assert 'id="safePipeline"' in html
    assert 'id="safePipelineProjectName"' in html
    assert 'id="safePipelineFile"' in html
    assert 'id="safePipelineRealLlmRequested"' in html
    assert html.index('id="safePipelineFile"') < html.index('id="safePipelineRealLlmRequested"')
    assert html.index('id="safePipelineRealLlmRequested"') < html.index('id="startSafePipeline"')
    assert 'id="useOfficialSafePipelineText"' in html
    assert 'id="startSafePipeline"' in html
    assert 'id="refreshSafePipeline"' in html
    assert 'id="safePipelineStatus"' in html
    assert 'id="safePipelineRunBadge"' in html
    assert 'id="safePipelineRunMessage"' in html
    assert "narrative_failure_summary" in html
    assert "pipeline_phase" in html
    assert "pipeline_safe_issue_codes" in html
    assert "PROVIDER_CHECKING" in html
    assert "pipelineTerminal" in html
    assert "provider_health" in html
    assert 'id="advancedDevelopmentDiagnostics"' in html
    assert 'id="advancedDevelopmentDiagnostics" open' not in html
    assert "/pipeline-runs/import-and-analyze" in html
    assert "batch_summary" in html
    assert "GATE2_PENDING" in html
    assert "叙事已完成，正在补齐 Gate 2 审核" in html
    assert "ensureSafePipelineRealLlmEnabled" in html
    assert "describeSafePipelineStartError" in html
    assert "START_FAILED" in html
    assert 'body.append("real_llm_requested", String(realLlmRequested))' in html
    assert "const stoppedAtGate2" in html
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
    assert '"context chunk ids"' in html
    assert '"owned chunk ids"' in html
    assert '"parent window"' in html
    assert '"split reason"' in html
    assert '"previous failure"' in html
    assert '"safe diagnostics"' in html
    assert "/narrative-analysis-runs/" in html
    assert "/documents/${encodeURIComponent(documentId)}/narrative-analysis-runs" in html
    advanced_start = html.index('id="advancedNarrativeDebug"')
    manual_chunk_input = html.index('id="narrativeChunkIds"')
    advanced_end = html.index("</details>", advanced_start)
    assert advanced_start < manual_chunk_input < advanced_end


def test_web_console_exposes_automatic_gate1_and_chapter_authorization() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="gate1ReviewDetails"' in html
    assert 'id="gate1ReviewSummary"' in html
    assert 'id="gate1ReviewPayload"' in html
    assert 'id="analysisChapterSelection"' in html
    assert "narrative-analysis-chapters" in html
    assert "approved_chunk_bundle" in html
    assert "state.selectedAnalysisChapters" in html
    assert "chapter_ids: state.selectedAnalysisChapters" in html
    assert "Gate 1 APPROVED" in html


def test_web_console_exposes_whole_document_outputs_for_manual_review() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="wholeDocumentSummary"' in html
    assert 'id="wholeDocumentFullProposal"' in html
    assert 'id="wholeDocumentProposalDetail"' in html
    assert "renderWholeDocumentSummary" in html
    assert "renderWholeDocumentProposalDetail" in html
    assert "data-whole-proposal-mode" in html
    assert "scheduleWholeDocumentProgressPoll" in html
    assert '"type", "basis", "subject / subtype"' in html


def test_web_console_exposes_readonly_automatic_gate2_route_summary() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="wholeDocumentGate2"' in html
    assert "review_gate2_route_decision" in html
    assert "review_gate2_approved_count" in html
    assert "review_gate2_rejected_count" in html
    assert "review_gate2_held_count" in html
    assert "/review-gate2" in html
    assert "runReviewGate2" not in html
    assert "forceReviewGate2" not in html


def test_web_console_exposes_readonly_recovery_summary_without_actions() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="wholeDocumentRecovery"' in html
    assert "/recovery" in html
    assert "runRecovery" not in html
    assert "forceRecovery" not in html


def test_web_console_exposes_readonly_timeline_gate3_summary() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="gate1ReviewSummary"' in html
    assert 'id="wholeDocumentSummary"' in html
    assert 'id="wholeDocumentGate2"' in html
    assert 'id="wholeDocumentTimelineGate3"' in html
    assert "/timeline-gate3/" in html
    assert "/timeline/analyze" not in html
    assert "runTimelineGate3" not in html
    assert "forceTimelineGate3" not in html
    assert "skipGate3" not in html
    assert "commitStoryBible" not in html


def test_web_console_exposes_a_separate_offline_knowledge_state_evaluation_area() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="knowledgeEvaluation"' in html
    assert 'id="loadKnowledgeEvaluationCases"' in html
    assert 'id="knowledgeEvaluationCaseList"' in html
    assert 'id="knowledgeEvaluationBatch"' in html
    assert 'id="evaluateKnowledgeStateBatch"' in html
    assert 'id="buildKnowledgeEvaluationReport"' in html
    assert 'id="knowledgeEvaluationReportStatus"' in html
    assert 'id="knowledgeEvaluationReport"' in html
    assert "已收集评测结果" in html
    assert 'id="runKnowledgeStateCase"' in html
    assert 'id="knowledgeEvaluationReviewNotes"' in html
    assert 'id="exportKnowledgeEvaluation"' in html
    assert "/knowledge-state-evaluation/cases" in html
    assert "不会在加载时调用 Provider" in html
    assert "real_llm_requested: true" in html
    assert "evaluation_result" in html
    assert "actual_structured_batch" in html
    assert "run_failures" in html
    assert "target_kind 错误" in html


def test_knowledge_state_evaluation_requires_case_selection_before_running() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="knowledgeEvaluationActionHint"' in html
    assert 'id="runKnowledgeStateCase" disabled' in html
    assert "function updateKnowledgeEvaluationActionUi()" in html
    assert "updateKnowledgeEvaluationActionUi();" in html


def test_knowledge_state_real_llm_evaluation_exposes_running_and_failure_feedback() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'id="knowledgeEvaluationRunStatus"' in html
    assert "knowledgeEvaluationRunInProgress" in html
    assert "const hasSelectedCase = Boolean(caseId);" in html
    assert "真实 LLM 评测正在运行" in html
    assert "真实 LLM 评测失败" in html
    assert "运行失败，未评测" in html
    assert "acceptance_eligible" in html
    assert "finally" in html
    assert "reviewed_at" in html
    evaluation_section = html[
        html.index('id="knowledgeEvaluation"') : html.index('id="runs"')
    ]
    assert "provider_result" not in evaluation_section


def test_knowledge_state_exports_declare_utf8_json_content_type() -> None:
    html = Path("web_console/index.html").read_text(encoding="utf-8")

    assert 'type: "application/json;charset=utf-8"' in html
    assert "new Blob([pretty(payload)]" in html
