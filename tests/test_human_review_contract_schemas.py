"""Non-blocking review-material contracts for the unified human-review design."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.repositories.human_review_repository import (
    HumanReviewConflictError,
    HumanReviewRepository,
)
from comic_agent.repositories.production_dossier_repository import ProductionDossierRepository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.human_review import HumanReviewDecision, HumanReviewSubmissionV1
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.review import (
    NarrativeExecutionBundleV1,
    NarrativeExecutionExcludedItemV1,
    NarrativeExecutionFailedWindowV1,
    NarrativeExecutionProvenanceV1,
    NarrativeExecutionStatus,
    ReviewableProposalEnvelopeV1,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
    ReviewIssueV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    ProductionDossierProvenanceV1,
    ProductionDossierV1,
    StoryBibleCanonicalSnapshotV1,
)
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisProposalV1,
    TimelineGate3IssueCode,
    TimelineGate3IssueSeverity,
    TimelineGate3IssueV1,
    TimelineReviewMaterialProvenanceV1,
    TimelineReviewMaterialV1,
)
from comic_agent.services.human_approved_storybible_input_builder import (
    HumanApprovedStoryBibleInputBuilder,
)
from comic_agent.services.human_approved_storybible_production_context import (
    HumanApprovedStoryBibleProductionContextBuilder,
)
from comic_agent.services.human_review_service import HumanReviewService
from comic_agent.services.production_dossier_builder import ProductionDossierBuilder


def _review_service() -> HumanReviewService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return HumanReviewService(HumanReviewRepository(session), ProductionDossierRepository(session))


def _evidence() -> EvidenceRefV1:
    return EvidenceRefV1(chunk_id="chunk-1", quote_text="The bell rang.")


def _event(proposal_id: str = "event-1") -> EventProposalV1:
    return EventProposalV1(
        proposal_id=proposal_id,
        event_type="SCHOOL_EVENT",
        summary="The bell rang.",
        evidence_refs=[_evidence()],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def _candidate(proposal_id: str = "event-1") -> ReviewableProposalEnvelopeV1:
    event = _event(proposal_id)
    return ReviewableProposalEnvelopeV1(
        mode="event_extraction",
        proposal_schema="EventProposalV1",
        proposal=event,
        agent_run_ids=["agent-run-1"],
        aggregated_evidence_refs=event.evidence_refs,
    )


def _gate2_issue() -> ReviewIssueV1:
    return ReviewIssueV1(
        issue_id="gate2-issue-1",
        code=ReviewIssueCode.HUMAN_DECISION_REQUIRED,
        category=ReviewIssueCategory.REFERENCE,
        severity=ReviewIssueSeverity.REVIEW_REQUIRED,
        sanitized_message="A reference requires human confirmation.",
    )


def _narrative_bundle() -> NarrativeExecutionBundleV1:
    candidate = _candidate()
    return NarrativeExecutionBundleV1(
        bundle_id="narrative-execution-1",
        project_id="project-1",
        document_id="document-1",
        status=NarrativeExecutionStatus.SUCCEEDED,
        candidates=[candidate, _candidate("event-2")],
        issues=[_gate2_issue()],
        evidence_refs=candidate.aggregated_evidence_refs,
        excluded_items=[
            NarrativeExecutionExcludedItemV1(
                proposal_id="event-excluded-1",
                proposal_schema="EventProposalV1",
                mode="event_extraction",
                reason="Excluded because its evidence could not be verified.",
                issue_ids=["gate2-issue-1"],
                evidence_refs=[_evidence()],
            )
        ],
        provenance=NarrativeExecutionProvenanceV1(
            analysis_run_id="analysis-run-1",
            gate1_review_id="gate1-review-1",
            gate2_review_run_id="gate2-review-1",
            source_chunk_ids=["chunk-1"],
            agent_run_ids=["agent-run-1"],
        ),
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def _timeline_material() -> TimelineReviewMaterialV1:
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1",
        source_event_id="event-1",
        target_event_id="event-2",
        relation="BEFORE",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )
    candidate = TimelineAnalysisProposalV1(
        proposal_id="timeline-candidate-1",
        project_id="project-1",
        temporal_relations=[relation],
        evidence_refs=[_evidence()],
        confidence=0.9,
    )
    issue = TimelineGate3IssueV1(
        issue_id="gate3-issue-1",
        issue_code=TimelineGate3IssueCode.AMBIGUOUS_ORDERING,
        severity=TimelineGate3IssueSeverity.REVIEW_REQUIRED,
        evidence_refs=[_evidence()],
        sanitized_message="The relative order needs human review.",
    )
    return TimelineReviewMaterialV1(
        material_id="timeline-material-1",
        project_id="project-1",
        narrative_execution_bundle_id="narrative-execution-1",
        timeline_run_id="timeline-run-1",
        timeline_candidate=candidate,
        temporal_relations=[relation],
        review_id="gate3-review-1",
        review_status=ReviewGate3Decision.NEEDS_HUMAN_REVIEW,
        issues=[issue],
        evidence_refs=[_evidence()],
        provenance=TimelineReviewMaterialProvenanceV1(
            source_chunk_ids=["chunk-1"],
            timeline_agent_run_id="timeline-agent-run-1",
            gate3_reviewer_agent_run_id="gate3-agent-run-1",
        ),
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def test_narrative_execution_bundle_preserves_candidates_and_exclusions() -> None:
    bundle = _narrative_bundle()

    assert bundle.status == NarrativeExecutionStatus.SUCCEEDED
    for status in (
        NarrativeExecutionStatus.SUCCEEDED,
        NarrativeExecutionStatus.PARTIAL_FAILED,
        NarrativeExecutionStatus.NEEDS_HUMAN_ACTION,
    ):
        assert (
            NarrativeExecutionBundleV1.model_validate(
                bundle.model_dump() | {"status": status}
            ).status
            == status
        )
    assert bundle.candidates[0].proposal.proposal_id == "event-1"
    assert bundle.excluded_items[0].proposal_id == "event-excluded-1"
    assert bundle.provenance.analysis_run_id == "analysis-run-1"

    with pytest.raises(ValidationError, match="cannot also be a candidate"):
        NarrativeExecutionBundleV1.model_validate(
            bundle.model_dump()
            | {
                "excluded_items": [
                    bundle.excluded_items[0].model_dump() | {"proposal_id": "event-1"}
                ]
            }
        )


def test_timeline_review_material_keeps_candidate_relations_and_review_findings() -> None:
    material = _timeline_material()

    assert material.review_status == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert material.temporal_relations == material.timeline_candidate.temporal_relations
    assert material.issues[0].issue_id == "gate3-issue-1"

    with pytest.raises(ValidationError, match="exactly match timeline_candidate"):
        TimelineReviewMaterialV1.model_validate(material.model_dump() | {"temporal_relations": []})


def test_production_dossier_references_noncanonical_material_and_findings() -> None:
    dossier = ProductionDossierV1(
        schema_version="1.0",
        dossier_id="dossier-1",
        project_id="project-1",
        document_id="document-1",
        narrative_execution_bundle_id="narrative-execution-1",
        timeline_review_material_id="timeline-material-1",
        gate2_findings=[_gate2_issue()],
        gate3_findings=_timeline_material().issues,
        evidence_refs=[_evidence()],
        provenance=ProductionDossierProvenanceV1(
            narrative_analysis_run_id="analysis-run-1",
            gate1_review_id="gate1-review-1",
            gate2_review_run_id="gate2-review-1",
            gate3_review_id="gate3-review-1",
            source_chunk_ids=["chunk-1"],
        ),
    )

    assert dossier.narrative_execution_bundle_id == "narrative-execution-1"
    assert dossier.timeline_review_material_id == "timeline-material-1"
    assert dossier.gate3_findings[0].issue_id == "gate3-issue-1"


def test_dossier_builder_preserves_success_material_for_human_review() -> None:
    narrative = _narrative_bundle().model_copy(update={"issues": []})
    timeline = _timeline_material().model_copy(
        update={"review_status": ReviewGate3Decision.APPROVED, "issues": []}
    )

    dossier = ProductionDossierBuilder().build(narrative=narrative, timeline=timeline)

    assert dossier.narrative_summary is not None
    assert dossier.narrative_summary.execution_status == NarrativeExecutionStatus.SUCCEEDED
    assert dossier.timeline_summary is not None
    assert dossier.timeline_summary.timeline_candidate == timeline.timeline_candidate


def test_dossier_builder_preserves_partial_failures_exclusions_and_execution_issues() -> None:
    narrative = _narrative_bundle().model_copy(
        update={
            "status": NarrativeExecutionStatus.PARTIAL_FAILED,
            "failed_windows": [
                NarrativeExecutionFailedWindowV1(
                    analysis_window_id="window-10",
                    mode="event_extraction",
                    chunk_ids=["chunk-1"],
                    status="EXHAUSTED",
                    failure_category="PROVIDER_TIMEOUT",
                )
            ],
        }
    )

    dossier = ProductionDossierBuilder().build(narrative=narrative, timeline=_timeline_material())

    assert dossier.narrative_summary is not None
    assert dossier.narrative_summary.execution_status == NarrativeExecutionStatus.PARTIAL_FAILED
    assert dossier.narrative_summary.failed_windows[0].analysis_window_id == "window-10"
    assert dossier.narrative_summary.excluded_items == narrative.excluded_items
    assert any(item.source_stage == "EXECUTION" for item in dossier.unified_issues)


def test_dossier_builder_preserves_needs_human_action_and_unknown_timeline_issue() -> None:
    narrative = _narrative_bundle().model_copy(
        update={"status": NarrativeExecutionStatus.NEEDS_HUMAN_ACTION}
    )
    unknown_issue = TimelineGate3IssueV1(
        issue_id="unknown-relation-1",
        issue_code=TimelineGate3IssueCode.UNKNOWN_EVENT_REFERENCE,
        severity=TimelineGate3IssueSeverity.REVIEW_REQUIRED,
        evidence_refs=[_evidence()],
        sanitized_message="A Timeline relation remains unknown.",
    )
    timeline = _timeline_material().model_copy(update={"issues": [unknown_issue]})

    dossier = ProductionDossierBuilder().build(narrative=narrative, timeline=timeline)

    assert dossier.narrative_summary is not None
    assert dossier.narrative_summary.execution_status == NarrativeExecutionStatus.NEEDS_HUMAN_ACTION
    assert [item.issue_id for item in dossier.gate3_findings] == ["unknown-relation-1"]
    assert any(item.source_issue_id == "unknown-relation-1" for item in dossier.unified_issues)


def test_dossier_builder_rejects_cross_project_material() -> None:
    timeline = _timeline_material().model_copy(update={"project_id": "project-other"})

    with pytest.raises(ValueError, match="one project"):
        ProductionDossierBuilder().build(narrative=_narrative_bundle(), timeline=timeline)


def test_dossier_builder_rejects_timeline_event_outside_narrative_candidates() -> None:
    relation = (
        _timeline_material()
        .temporal_relations[0]
        .model_copy(update={"target_event_id": "event-not-in-narrative"})
    )
    timeline = _timeline_material().model_copy(
        update={
            "temporal_relations": [relation],
            "timeline_candidate": _timeline_material().timeline_candidate.model_copy(
                update={"temporal_relations": [relation]}
            ),
        }
    )

    with pytest.raises(ValueError, match="Narrative execution candidates"):
        ProductionDossierBuilder().build(narrative=_narrative_bundle(), timeline=timeline)


def _dossier() -> ProductionDossierV1:
    return ProductionDossierBuilder().build(
        narrative=_narrative_bundle(), timeline=_timeline_material()
    )


def _submission(
    decision: HumanReviewDecision, *, project_id: str = "project-1"
) -> HumanReviewSubmissionV1:
    return HumanReviewSubmissionV1(
        project_id=project_id,
        dossier_id=_dossier().dossier_id,
        decision=decision,
        reviewer_id="reviewer-1",
        reviewer_note="Human review decision recorded.",
    )


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        (HumanReviewDecision.APPROVE, "READY_FOR_STORYBIBLE"),
        (HumanReviewDecision.REJECT, "REJECTED_BY_HUMAN"),
        (HumanReviewDecision.REQUEST_CHANGES, "NEEDS_REVISION"),
    ],
)
def test_unified_human_review_records_each_legal_decision(
    decision: HumanReviewDecision, expected_status: str
) -> None:
    dossier = _dossier()
    result = _review_service().review(dossier=dossier, submission=_submission(decision))

    assert result.status == expected_status
    assert result.review_run.reviewer_note == "Human review decision recorded."
    assert result.review_run.lineage.source_dossier_id == dossier.dossier_id
    assert (
        result.review_run.lineage.narrative_execution_bundle_id
        == dossier.narrative_execution_bundle_id
    )


def test_unified_human_review_is_idempotent_but_rejects_decision_overwrite() -> None:
    dossier = _dossier()
    service = _review_service()
    first = service.review(dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE))
    repeated = service.review(dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE))

    assert repeated == first
    with pytest.raises(HumanReviewConflictError, match="different human decision"):
        service.review(dossier=dossier, submission=_submission(HumanReviewDecision.REJECT))


def test_unified_human_review_rejects_cross_project_and_invalid_dossier_lineage() -> None:
    dossier = _dossier()
    service = _review_service()

    with pytest.raises(ValueError, match="project and id"):
        service.review(
            dossier=dossier,
            submission=_submission(HumanReviewDecision.APPROVE, project_id="other"),
        )
    with pytest.raises(ValueError, match="complete 1.2"):
        service.review(
            dossier=dossier.model_copy(update={"schema_version": "1.0"}),
            submission=_submission(HumanReviewDecision.APPROVE),
        )


@pytest.mark.parametrize(
    ("decision", "failure_code"),
    [
        (HumanReviewDecision.REJECT, "HUMAN_REVIEW_NOT_APPROVED"),
        (HumanReviewDecision.REQUEST_CHANGES, "HUMAN_REVIEW_NOT_APPROVED"),
    ],
)
def test_human_approved_storybible_input_builder_rejects_non_approvals(
    decision: HumanReviewDecision, failure_code: str
) -> None:
    dossier = _dossier()
    review = _review_service().review(dossier=dossier, submission=_submission(decision))

    result = HumanApprovedStoryBibleInputBuilder().build(dossier=dossier, review=review)

    assert result.production_input is None
    assert result.failure_code == failure_code


def test_human_approved_storybible_input_builder_preserves_full_lineage() -> None:
    dossier = _dossier()
    review = _review_service().review(
        dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE)
    )

    result = HumanApprovedStoryBibleInputBuilder().build(dossier=dossier, review=review)

    assert result.failure_code is None
    assert result.production_input is not None
    production_input = result.production_input
    assert production_input.human_review_id == review.review_run.review_id
    assert production_input.dossier_id == dossier.dossier_id
    assert production_input.narrative_execution_bundle_id == dossier.narrative_execution_bundle_id
    assert production_input.timeline_review_material_id == dossier.timeline_review_material_id
    assert production_input.evidence_refs == dossier.evidence_refs


def test_human_approved_storybible_input_builder_returns_structured_lineage_failures() -> None:
    dossier = _dossier()
    review = _review_service().review(
        dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE)
    )
    builder = HumanApprovedStoryBibleInputBuilder()

    cross_project = review.model_copy(
        update={"review_run": review.review_run.model_copy(update={"project_id": "other"})}
    )
    assert builder.build(dossier=dossier, review=cross_project).failure_code == "PROJECT_MISMATCH"
    bad_lineage = review.model_copy(
        update={
            "review_run": review.review_run.model_copy(
                update={
                    "lineage": review.review_run.lineage.model_copy(
                        update={"source_dossier_id": "other"}
                    )
                }
            )
        }
    )
    assert builder.build(dossier=dossier, review=bad_lineage).failure_code == "LINEAGE_MISMATCH"


def _human_approved_input():  # type: ignore[no-untyped-def]
    dossier = _dossier()
    review = _review_service().review(
        dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE)
    )
    result = HumanApprovedStoryBibleInputBuilder().build(dossier=dossier, review=review)
    assert result.production_input is not None
    return dossier, result.production_input


def _context_chunk() -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text="The bell rang.",
        checksum="safe",
    )


def test_human_approved_context_boundary_preserves_full_artifact_lineage() -> None:
    dossier, production_input = _human_approved_input()
    context = HumanApprovedStoryBibleProductionContextBuilder().build(
        production_input=production_input,
        dossier=dossier,
        narrative=_narrative_bundle(),
        timeline=_timeline_material(),
        canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
        source_chunks=[_context_chunk()],
    )

    assert context.human_review_id == production_input.human_review_id
    assert context.human_review_decision == "APPROVE"
    assert context.reviewer_id == production_input.reviewer_id
    assert context.review_time == production_input.review_time
    assert context.dossier_id == dossier.dossier_id
    assert context.narrative_execution_bundle_id == dossier.narrative_execution_bundle_id
    assert context.timeline_review_material_id == dossier.timeline_review_material_id
    assert [event.proposal_id for event in context.human_approved_events] == [
        "event-1",
        "event-2",
    ]
    assert [issue.issue_id for issue in context.narrative_issues] == ["gate2-issue-1"]
    assert [item.proposal_id for item in context.excluded_items] == ["event-excluded-1"]
    assert context.timeline_review_status == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert [issue.issue_id for issue in context.timeline_issues] == ["gate3-issue-1"]


def test_durable_dossier_context_rebuilds_only_persisted_human_approved_material() -> None:
    dossier = _dossier()
    review = _review_service().review(
        dossier=dossier, submission=_submission(HumanReviewDecision.APPROVE)
    )

    context = HumanApprovedStoryBibleProductionContextBuilder().build_from_durable_dossier(
        review=review.review_run,
        dossier=dossier,
        canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
        source_chunks=[_context_chunk()],
    )

    assert [event.proposal_id for event in context.human_approved_events] == ["event-1", "event-2"]
    assert context.human_review_id == review.review_run.review_id
    assert context.dossier_id == dossier.dossier_id


def test_human_approved_context_boundary_rejects_mismatched_lineage_and_scope() -> None:
    dossier, production_input = _human_approved_input()
    builder = HumanApprovedStoryBibleProductionContextBuilder()
    with pytest.raises(ValueError, match="lineage does not match"):
        builder.build(
            production_input=production_input.model_copy(
                update={"narrative_execution_bundle_id": "wrong"}
            ),
            dossier=dossier,
            narrative=_narrative_bundle(),
            timeline=_timeline_material(),
            canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
            source_chunks=[_context_chunk()],
        )
    with pytest.raises(ValueError, match="exactly cover"):
        builder.build(
            production_input=production_input,
            dossier=dossier,
            narrative=_narrative_bundle(),
            timeline=_timeline_material(),
            canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
            source_chunks=[],
        )
    with pytest.raises(ValueError, match="must not contain duplicate"):
        builder.build(
            production_input=production_input,
            dossier=dossier,
            narrative=_narrative_bundle(),
            timeline=_timeline_material(),
            canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
            source_chunks=[_context_chunk(), _context_chunk()],
        )
