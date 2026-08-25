"""Regression contracts for the Gate 2 -> Timeline -> Gate 3 boundary."""

import pytest

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import TemporalRelationProposalV1
from comic_agent.schemas.reliability import ProviderFailureCategory
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineGate3IssueCode,
)
from comic_agent.schemas.timeline_execution import (
    TimelineExecutionBundleV1,
    TimelineExecutionDiagnosticV1,
    TimelineExecutionFailedItemV1,
    TimelineExecutionInputReferenceV1,
    TimelineExecutionProvenanceV1,
    TimelineExecutionStatus,
)
from comic_agent.services.review_gate3_service import ReviewGate3Service


def _evidence() -> EvidenceRefV1:
    return EvidenceRefV1(chunk_id="chunk-1", quote_text="The bell rings")


def _execution_bundle(
    status: TimelineExecutionStatus,
) -> TimelineExecutionBundleV1:
    failed_items = []
    diagnostics = []
    if status != TimelineExecutionStatus.SUCCEEDED:
        failed_items = [
            TimelineExecutionFailedItemV1(
                pair_id="pair-event-1-event-2",
                failure_category=ProviderFailureCategory.SCHEMA,
                field_path="temporal_relations.0.relation",
                failure_origin="LLM_OUTPUT_SCHEMA_INVALID",
                safe_issue_codes=["TIMELINE_PAIR_SCHEMA_INVALID"],
            )
        ]
        diagnostics = [
            TimelineExecutionDiagnosticV1(
                failure_origin="LLM_OUTPUT_SCHEMA_INVALID",
                field_path="temporal_relations.0.relation",
                error_type="literal_error",
                message_type="enum_error",
            )
        ]
    return TimelineExecutionBundleV1(
        bundle_id=f"timeline-execution-{status.value.lower()}",
        project_id="project-1",
        timeline_run_id="timeline-run-1",
        status=status,
        input_reference=TimelineExecutionInputReferenceV1(
            source_approved_proposal_bundle_id="bundle-1",
            source_gate2_review_id="gate2-review-1",
            source_gate2_route_id="gate2-route-1",
            event_proposal_ids=["event-1", "event-2"],
        ),
        failed_items=failed_items,
        diagnostics=diagnostics,
        evidence_refs=[_evidence()],
        provenance=TimelineExecutionProvenanceV1(
            timeline_agent_run_id="timeline-agent-run-1"
        ),
    )


def test_gate3_rejects_unknown_event_reference_without_bundle() -> None:
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1", source_event_id="event-1", target_event_id="missing-event",
        relation="BEFORE", evidence_refs=[_evidence()], confidence=0.9,
    )
    result, route = ReviewGate3Service().review(
        project_id="project-1", source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1", reviewer_agent_run_id="gate3-run-1",
        event_ids=["event-1"], temporal_relations=[relation], evidence_refs=[_evidence()],
    )

    assert result.decision == ReviewGate3Decision.REJECTED
    assert result.issues[0].issue_code == TimelineGate3IssueCode.UNKNOWN_EVENT_REFERENCE
    assert route.approved_timeline_bundle is None


def test_gate3_approves_in_scope_timeline_and_returns_typed_bundle() -> None:
    result, route = ReviewGate3Service().review(
        project_id="project-1", source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1", reviewer_agent_run_id="gate3-run-1",
        event_ids=["event-1"], temporal_relations=[], evidence_refs=[_evidence()],
    )

    assert result.decision == ReviewGate3Decision.APPROVED
    assert route.approved_timeline_bundle is not None
    assert route.approved_timeline_bundle.source_approved_proposal_bundle_id == "bundle-1"


def test_gate3_approves_succeeded_timeline_execution_bundle() -> None:
    execution = _execution_bundle(TimelineExecutionStatus.SUCCEEDED)

    result, route = ReviewGate3Service().review(
        project_id="project-1",
        source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1",
        reviewer_agent_run_id="gate3-run-1",
        event_ids=["event-1", "event-2"],
        temporal_relations=[],
        evidence_refs=[_evidence()],
        timeline_execution_bundle=execution,
    )

    assert result.decision == ReviewGate3Decision.APPROVED
    assert result.timeline_execution_bundle_id == execution.bundle_id
    assert route.timeline_execution_bundle_id == execution.bundle_id


@pytest.mark.parametrize(
    "status",
    [
        TimelineExecutionStatus.PARTIAL_FAILED,
        TimelineExecutionStatus.NEEDS_HUMAN_ACTION,
        TimelineExecutionStatus.FAILED,
    ],
)
def test_gate3_holds_non_succeeded_execution_bundle_with_safe_diagnostics(
    status: TimelineExecutionStatus,
) -> None:
    execution = _execution_bundle(status)

    result, route = ReviewGate3Service().review(
        project_id="project-1",
        source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1",
        reviewer_agent_run_id="gate3-run-1",
        event_ids=["event-1", "event-2"],
        temporal_relations=[],
        evidence_refs=[_evidence()],
        timeline_execution_bundle=execution,
    )

    assert result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert route.route == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    issue = result.issues[0]
    assert issue.issue_code == TimelineGate3IssueCode.REVIEW_EXECUTION_FAILED
    assert issue.related_pair_ids == ["pair-event-1-event-2"]
    assert issue.execution_failure_categories == [ProviderFailureCategory.SCHEMA]
    assert issue.execution_diagnostic_field_paths == ["temporal_relations.0.relation"]
    assert issue.failed_item_count == 1
    serialized = result.model_dump_json()
    assert "raw LLM response" not in serialized
    assert "Authorization" not in serialized


def test_ambiguous_ordering_is_held_not_automatically_recoverable() -> None:
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1", source_event_id="event-1", target_event_id="event-2",
        relation="UNKNOWN", confidence=0.9,
    )
    result, route = ReviewGate3Service().review(
        project_id="project-1", source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1", reviewer_agent_run_id="gate3-run-1",
        event_ids=["event-1", "event-2"],
        temporal_relations=[relation],
        evidence_refs=[_evidence()],
    )

    assert result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert result.issues[0].recoverable is False
    assert route.held_issue_ids


def test_gate3_failed_route_is_sanitized_and_never_exposes_a_bundle() -> None:
    result, route = ReviewGate3Service().failed(
        project_id="project-1",
        source_approved_proposal_bundle_id="bundle-1",
        timeline_run_id="timeline-run-1",
        reviewer_agent_run_id="gate3-run-1",
    )

    assert result.decision == ReviewGate3Decision.FAILED
    assert route.route == ReviewGate3Decision.FAILED
    assert route.approved_timeline_bundle is None
    assert route.safe_issue_codes == [TimelineGate3IssueCode.REVIEW_EXECUTION_FAILED]
