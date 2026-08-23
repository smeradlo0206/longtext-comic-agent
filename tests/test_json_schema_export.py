import json

from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    ApprovedSourceChunkBundleV1,
    CampusContentProfileProposalV1,
    ComicBeatProposalV1,
    EvidenceReviewItemV1,
    NarrativeAnalysisReviewRouteV1,
    NarrativeAnalysisWindowPlanV1,
    NarrativeAnalysisWindowV1,
    ProposalRecoveryDiagnosticV1,
    ProposalReviewDecision,
    ProposalReviewDecisionV1,
    ReferenceResolutionBasis,
    ReferenceResolutionDecisionV1,
    ReferenceResolutionStatus,
    ReferenceTargetCandidateV1,
    RelationshipAssertionPolarity,
    RelationshipContextEventRefV1,
    RelationshipDirectionality,
    RelationshipDomain,
    RelationshipEvidenceBasis,
    RelationshipKind,
    RelationshipParticipantKind,
    RelationshipParticipantRefV1,
    RelationshipResolutionStatus,
    RelationshipSignalEffect,
    RelationshipSignalProposalBatchV1,
    RelationshipSignalProposalV1,
    RelationshipSourceSpeakerRefV1,
    RelationshipSupportLevel,
    RelationshipTemporalAnchorV1,
    ReviewableProposalEnvelopeV1,
    ReviewableProposalMode,
    ReviewCheckStatus,
    ReviewGate1CategoryCountV1,
    ReviewGate1Check,
    ReviewGate1CheckResultV1,
    ReviewGate1InputV1,
    ReviewGate1IssueCategory,
    ReviewGate1IssueCode,
    ReviewGate1IssueCountV1,
    ReviewGate1IssueV1,
    ReviewGate1MetricsV1,
    ReviewGate1PolicyV1,
    ReviewGate1ResultV1,
    ReviewGate1RoutingAdviceV1,
    ReviewGate1RunStatus,
    ReviewGate2InputV1,
    ReviewGate2PolicyV1,
    ReviewGate2ResultV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
    ReviewIssueV1,
    ReviewMethod,
    SourceChapterReviewItemV1,
    SourceChunkReviewItemV1,
    SourceChunkUsability,
    SourceReviewDecision,
    SourceTextAuditSnapshotV1,
    StateChangeAttributePath,
    StateChangeEventRefV1,
    StateChangeProposalBatchV1,
    StateChangeTargetKind,
    StateChangeTargetRefV1,
)
from scripts import export_json_schemas


def test_json_schema_export_includes_phase_one_workflow_schemas(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    export_json_schemas.main()

    output_dir = tmp_path / "schema_exports"
    assert (output_dir / "AgentRunV1.json").exists()
    assert (output_dir / "ProviderResultV1.json").exists()
    assert (output_dir / "ProviderCapabilityProfileV1.json").exists()
    assert (output_dir / "ProviderExecutionMetadataV1.json").exists()
    assert (output_dir / "MockProviderResultV1.json").exists()
    assert (output_dir / "EntityProposalBatchV1.json").exists()
    assert (output_dir / "ClaimProposalBatchV1.json").exists()
    assert (output_dir / "ClaimProposalV1.json").exists()
    assert (output_dir / "CampusContentProfileProposalV1.json").exists()
    assert (output_dir / "ComicBeatProposalV1.json").exists()
    assert (output_dir / "KnowledgeStateProposalV1.json").exists()
    assert (output_dir / "KnowledgeStateProposalBatchV1.json").exists()
    assert (output_dir / "KnowledgeStateEvaluationReportV1.json").exists()
    assert (output_dir / "KnowledgeStateEvaluationReportRequestV1.json").exists()
    assert (output_dir / "KnowledgeStateEvaluationRunFailureV1.json").exists()
    assert (output_dir / "KnowledgeStateEvaluationFailureDiagnosticsV1.json").exists()
    assert (output_dir / "StateChangeProposalV1.json").exists()
    assert (output_dir / "StateChangeProposalBatchV1.json").exists()
    assert (output_dir / "StateChangeEventRefV1.json").exists()
    assert (output_dir / "StateChangeTargetRefV1.json").exists()
    assert (output_dir / "NarrativeAnalysisResultV1.json").exists()
    assert (output_dir / "NarrativeAnalysisWindowPlanV1.json").exists()
    assert (output_dir / "NarrativeAnalysisWindowV1.json").exists()
    assert (output_dir / "NarrativeAnalysisBatchV1.json").exists()
    assert (output_dir / "NarrativeGate2HandoffV1.json").exists()
    assert (output_dir / "RelationshipParticipantRefV1.json").exists()
    assert (output_dir / "RelationshipTemporalAnchorV1.json").exists()
    assert (output_dir / "RelationshipContextEventRefV1.json").exists()
    assert (output_dir / "RelationshipSignalProposalV1.json").exists()
    assert (output_dir / "RelationshipSignalProposalBatchV1.json").exists()
    assert (output_dir / "AggregatedRelationshipSignalProposalV1.json").exists()
    assert (output_dir / "ReviewGate2InputV1.json").exists()
    assert (output_dir / "ReviewGate2PolicyV1.json").exists()
    assert (output_dir / "ReviewGate2ResultV1.json").exists()
    assert (output_dir / "NarrativeAnalysisReviewRouteV1.json").exists()
    assert (output_dir / "ProposalRecoveryDiagnosticV1.json").exists()
    assert (output_dir / "ProposalMentionRefV1.json").exists()
    assert (output_dir / "ReviewIssueV1.json").exists()
    assert (output_dir / "ReferenceResolutionDecisionV1.json").exists()
    assert (output_dir / "ReviewableProposalEnvelopeV1.json").exists()
    assert (output_dir / "ProposalReviewDecisionV1.json").exists()
    assert (output_dir / "ApprovedProposalBundleV1.json").exists()
    for schema_name in (
        "NarrativeExecutionBundleV1",
        "NarrativeExecutionExcludedItemV1",
        "NarrativeExecutionFailedWindowV1",
        "NarrativeExecutionProvenanceV1",
        "TimelineReviewMaterialV1",
        "TimelineReviewMaterialProvenanceV1",
        "ProductionDossierV1",
        "ProductionDossierProvenanceV1",
        "StoryBibleProductionInputV2",
        "StoryBibleProductionInputBuildResultV1",
        "HumanReviewLineageV1",
        "HumanReviewSubmissionV1",
        "HumanReviewRunV1",
        "HumanReviewResultV1",
        "HumanApprovedStoryBibleProductionContextV1",
        "HumanApprovedStoryBibleProductionLineageV1",
        "StoryBibleProductionAuthorizationFailureV1",
        "ComicPlanningInputV1",
    ):
        assert (output_dir / f"{schema_name}.json").exists()
    for schema_name in (
        "ApprovedStoryBibleBundleV1",
        "StoryBibleReviewContextV1",
        "StoryBibleReviewResultV1",
        "StoryBibleReviewRunV1",
        "StoryBibleEvidenceCheckV1",
        "StoryBibleReviewIssueV1",
        "StoryBibleReviewMetadataV1",
    ):
        assert (output_dir / f"{schema_name}.json").exists()

    approved_storybible_schema = json.loads(
        (output_dir / "ApprovedStoryBibleBundleV1.json").read_text(encoding="utf-8")
    )
    assert "entities" in approved_storybible_schema["properties"]
    assert "source_storybible_run_id" in approved_storybible_schema["required"]
    assert approved_storybible_schema["additionalProperties"] is False
    for schema_name in (
        "SourceTextAuditSnapshotV1",
        "ReviewGate1PolicyV1",
        "ReviewGate1InputV1",
        "ReviewGate1IssueV1",
        "ReviewGate1CheckResultV1",
        "SourceChapterReviewItemV1",
            "SourceChunkReviewItemV1",
            "ApprovedSourceChunkBundleV1",
            "ReviewGate1IssueCountV1",
            "ReviewGate1CategoryCountV1",
            "ReviewGate1MetricsV1",
            "ReviewGate1RoutingAdviceV1",
            "ReviewGate1ResultV1",
    ):
        assert (output_dir / f"{schema_name}.json").exists()

    event_schema = json.loads((output_dir / "EventProposalV1.json").read_text(encoding="utf-8"))
    claim_schema = json.loads((output_dir / "ClaimProposalV1.json").read_text(encoding="utf-8"))
    knowledge_schema = json.loads(
        (output_dir / "KnowledgeStateProposalV1.json").read_text(encoding="utf-8")
    )
    state_change_schema = json.loads(
        (output_dir / "StateChangeProposalV1.json").read_text(encoding="utf-8")
    )
    state_change_batch_schema = json.loads(
        (output_dir / "StateChangeProposalBatchV1.json").read_text(encoding="utf-8")
    )
    result_schema = json.loads(
        (output_dir / "NarrativeAnalysisResultV1.json").read_text(encoding="utf-8")
    )
    window_schema = json.loads(
        (output_dir / "NarrativeAnalysisWindowV1.json").read_text(encoding="utf-8")
    )
    relationship_schema = json.loads(
        (output_dir / "RelationshipSignalProposalV1.json").read_text(encoding="utf-8")
    )
    relationship_batch_schema = json.loads(
        (output_dir / "RelationshipSignalProposalBatchV1.json").read_text(encoding="utf-8")
    )
    source_chunk_schema = json.loads(
        (output_dir / "SourceChunkV1.json").read_text(encoding="utf-8")
    )
    review_input_schema = json.loads(
        (output_dir / "ReviewGate2InputV1.json").read_text(encoding="utf-8")
    )
    review_policy_schema = json.loads(
        (output_dir / "ReviewGate2PolicyV1.json").read_text(encoding="utf-8")
    )
    review_result_schema = json.loads(
        (output_dir / "ReviewGate2ResultV1.json").read_text(encoding="utf-8")
    )
    review_envelope_schema = json.loads(
        (output_dir / "ReviewableProposalEnvelopeV1.json").read_text(encoding="utf-8")
    )
    gate1_result_schema = json.loads(
        (output_dir / "ReviewGate1ResultV1.json").read_text(encoding="utf-8")
    )
    gate1_policy_schema = json.loads(
        (output_dir / "ReviewGate1PolicyV1.json").read_text(encoding="utf-8")
    )

    assert "actor_resolution_status" in event_schema["properties"]
    assert "evidence_refs" in event_schema["properties"]
    assert "confidence" in event_schema["properties"]
    assert "evidence_refs" in event_schema["required"]
    assert "confidence" in event_schema["required"]
    assert event_schema["additionalProperties"] is False
    assert event_schema["properties"]["confidence"]["minimum"] == 0
    assert event_schema["properties"]["confidence"]["maximum"] == 1
    assert "claim_type" in claim_schema["properties"]
    assert "temporal_scope" in claim_schema["properties"]
    assert "verification_status" in claim_schema["properties"]
    assert "evidence_refs" in claim_schema["required"]
    assert claim_schema["additionalProperties"] is False
    assert "epistemic_status" in knowledge_schema["properties"]
    assert "subject" in knowledge_schema["properties"]
    assert "target" in knowledge_schema["properties"]
    assert "epistemic_basis" in knowledge_schema["properties"]
    assert "evidence_refs" in knowledge_schema["required"]
    assert knowledge_schema["additionalProperties"] is False
    assert state_change_schema["properties"]["schema_version"]["enum"] == [
        "1.0",
        "1.1",
        "1.2",
        "1.3",
    ]
    assert "event" in state_change_schema["properties"]
    assert "target" in state_change_schema["properties"]
    assert "new_value_evidence_indexes" in state_change_schema["properties"]
    assert "persistence_evidence_indexes" in state_change_schema["properties"]
    assert state_change_batch_schema["properties"]["schema_version"]["enum"] == [
        "1.1",
        "1.2",
        "1.3",
    ]
    assert "appearance.clothing" in json.dumps(state_change_schema)
    assert "appearance.hairstyle" in json.dumps(state_change_schema)
    assert result_schema["properties"]["schema_version"]["enum"] == [
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
    ]
    assert "state_changes" in result_schema["properties"]
    assert "relationship_signals" in result_schema["properties"]
    assert StateChangeEventRefV1.__name__ == "StateChangeEventRefV1"
    assert StateChangeTargetRefV1.__name__ == "StateChangeTargetRefV1"
    assert StateChangeProposalBatchV1.__name__ == "StateChangeProposalBatchV1"
    assert NarrativeAnalysisWindowPlanV1.__name__ == "NarrativeAnalysisWindowPlanV1"
    assert NarrativeAnalysisWindowV1.__name__ == "NarrativeAnalysisWindowV1"
    assert window_schema["properties"]["schema_version"]["enum"] == [
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
            "1.5",
            "1.6",
            "1.7",
            "1.8",
            "1.9",
        ]
    assert "owned_chunk_ids" in window_schema["properties"]
    assert "parent_window_id" in window_schema["properties"]
    assert relationship_schema["properties"]["schema_version"]["const"] == "1.0"
    assert relationship_schema["properties"]["subject"]
    assert relationship_schema["properties"]["counterpart"]
    assert relationship_schema["properties"]["evidence_basis"]
    assert relationship_schema["properties"]["temporal_anchor"]
    assert relationship_batch_schema["properties"]["signals"]
    assert "source-first" in relationship_schema["description"].lower()
    relationship_text = json.dumps(relationship_schema, ensure_ascii=False)
    for enum_value in (
        "CHARACTER",
        "ORGANIZATION",
        "DIRECTED",
        "SYMMETRIC",
        "DENIAL",
        "UNRESOLVED",
        "EntityProposalV1",
        "EventProposalV1",
    ):
        assert enum_value in relationship_text
    assert "relationship_signals" in result_schema["properties"]
    assert RelationshipAssertionPolarity.DENIED == "DENIED"
    assert RelationshipDirectionality.SYMMETRIC == "SYMMETRIC"
    assert RelationshipDomain.TRUST == "TRUST"
    assert RelationshipEvidenceBasis.NARRATED == "NARRATED"
    assert RelationshipKind.TRUSTS == "TRUSTS"
    assert RelationshipParticipantKind.CHARACTER == "CHARACTER"
    assert RelationshipResolutionStatus.UNRESOLVED == "UNRESOLVED"
    assert RelationshipSignalEffect.PRESENT == "PRESENT"
    assert RelationshipSupportLevel.LIMITED == "LIMITED"
    assert RelationshipSourceSpeakerRefV1.__name__ == "RelationshipSourceSpeakerRefV1"
    assert RelationshipParticipantRefV1.__name__ == "RelationshipParticipantRefV1"
    assert RelationshipTemporalAnchorV1.__name__ == "RelationshipTemporalAnchorV1"
    assert RelationshipContextEventRefV1.__name__ == "RelationshipContextEventRefV1"
    assert RelationshipSignalProposalV1.__name__ == "RelationshipSignalProposalV1"
    assert RelationshipSignalProposalBatchV1.__name__ == "RelationshipSignalProposalBatchV1"
    assert StateChangeTargetKind.LOCATION == "LOCATION"
    assert StateChangeAttributePath.QUANTITY == "quantity"
    assert "char_start" in source_chunk_schema["properties"]
    assert "char_end" in source_chunk_schema["properties"]
    assert "checksum" in source_chunk_schema["properties"]
    assert review_input_schema["properties"]["schema_version"]["const"] == "1.0"
    assert review_policy_schema["properties"]["schema_version"]["const"] == "1.0"
    assert gate1_policy_schema["properties"]["schema_version"]["enum"] == ["1.0", "1.1"]
    assert "max_warning_whitespace_run" in gate1_policy_schema["properties"]
    assert "review_required_whitespace_run" in gate1_policy_schema["properties"]
    assert review_result_schema["properties"]["schema_version"]["enum"] == ["1.0", "1.1"]
    review_text = json.dumps(review_envelope_schema, ensure_ascii=False)
    for proposal_name in (
        "EventProposalV1",
        "EntityProposalV1",
        "ClaimProposalV1",
        "KnowledgeStateProposalV1",
        "StateChangeProposalV1",
        "RelationshipSignalProposalV1",
    ):
        assert proposal_name in review_text
    policy_text = json.dumps(review_policy_schema, ensure_ascii=False)
    assert "allow_canonical_writes" in policy_text
    assert "allow_fuzzy_reference_matching" in policy_text
    assert "allow_llm_reference_resolution" in policy_text
    assert "provider_response" not in policy_text
    assert ApprovedProposalBundleV1.__name__ == "ApprovedProposalBundleV1"
    assert CampusContentProfileProposalV1.__name__ == "CampusContentProfileProposalV1"
    assert ComicBeatProposalV1.__name__ == "ComicBeatProposalV1"
    assert ApprovedProposalItemV1.__name__ == "ApprovedProposalItemV1"
    assert EvidenceReviewItemV1.__name__ == "EvidenceReviewItemV1"
    assert ProposalReviewDecision.APPROVED == "APPROVED"
    assert ProposalReviewDecisionV1.__name__ == "ProposalReviewDecisionV1"
    assert ReferenceResolutionBasis.NONE == "NONE"
    assert ReferenceResolutionDecisionV1.__name__ == "ReferenceResolutionDecisionV1"
    assert ReferenceResolutionStatus.AMBIGUOUS == "AMBIGUOUS"
    assert ReferenceTargetCandidateV1.__name__ == "ReferenceTargetCandidateV1"
    assert ReviewCheckStatus.PASSED == "PASSED"
    assert ReviewGate2InputV1.__name__ == "ReviewGate2InputV1"
    assert ReviewGate2PolicyV1.__name__ == "ReviewGate2PolicyV1"
    assert ReviewGate2ResultV1.__name__ == "ReviewGate2ResultV1"
    assert ReviewGate2RunStatus.COMPLETED == "COMPLETED"
    assert ReviewGate2RoutingDecision.APPROVED == "APPROVED"
    assert NarrativeAnalysisReviewRouteV1.__name__ == "NarrativeAnalysisReviewRouteV1"
    assert ProposalRecoveryDiagnosticV1.__name__ == "ProposalRecoveryDiagnosticV1"
    assert ReviewIssueCategory.PROVENANCE == "PROVENANCE"
    assert ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND == "EVIDENCE_QUOTE_NOT_FOUND"
    assert ReviewIssueSeverity.BLOCKING == "BLOCKING"
    assert ReviewIssueV1.__name__ == "ReviewIssueV1"
    assert ReviewMethod.DETERMINISTIC == "DETERMINISTIC"
    assert ReviewableProposalEnvelopeV1.__name__ == "ReviewableProposalEnvelopeV1"
    assert ReviewableProposalMode.STATE_CHANGE_EXTRACTION == "state_change_extraction"
    gate1_result_text = json.dumps(gate1_result_schema, ensure_ascii=False)
    for forbidden in ('"normalized_text"', '"storage_uri"', '"raw_output"', '"provider_response"'):
        assert forbidden not in gate1_result_text
    assert ApprovedSourceChunkBundleV1.__name__ == "ApprovedSourceChunkBundleV1"
    assert ReviewGate1Check.DOCUMENT_TEXT == "DOCUMENT_TEXT"
    assert ReviewGate1CheckResultV1.__name__ == "ReviewGate1CheckResultV1"
    assert ReviewGate1InputV1.__name__ == "ReviewGate1InputV1"
    assert ReviewGate1IssueCategory.RANGE == "RANGE"
    assert ReviewGate1IssueCode.CHUNK_RANGE_OVERLAP == "CHUNK_RANGE_OVERLAP"
    assert ReviewGate1IssueV1.__name__ == "ReviewGate1IssueV1"
    assert ReviewGate1PolicyV1.__name__ == "ReviewGate1PolicyV1"
    assert ReviewGate1ResultV1.__name__ == "ReviewGate1ResultV1"
    assert ReviewGate1IssueCountV1.__name__ == "ReviewGate1IssueCountV1"
    assert ReviewGate1CategoryCountV1.__name__ == "ReviewGate1CategoryCountV1"
    assert ReviewGate1MetricsV1.__name__ == "ReviewGate1MetricsV1"
    assert ReviewGate1RoutingAdviceV1.__name__ == "ReviewGate1RoutingAdviceV1"
    assert ReviewGate1RunStatus.FAILED == "FAILED"
    assert SourceChapterReviewItemV1.__name__ == "SourceChapterReviewItemV1"
    assert SourceChunkReviewItemV1.__name__ == "SourceChunkReviewItemV1"
    assert SourceChunkUsability.USABLE == "USABLE"
    assert SourceReviewDecision.APPROVED == "APPROVED"
    assert SourceTextAuditSnapshotV1.__name__ == "SourceTextAuditSnapshotV1"
