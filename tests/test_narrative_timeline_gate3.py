"""Regression contracts for the Gate 2 -> Timeline -> Gate 3 boundary."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import TemporalRelationProposalV1
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineGate3IssueCode,
)
from comic_agent.services.review_gate3_service import ReviewGate3Service


def _evidence() -> EvidenceRefV1:
    return EvidenceRefV1(chunk_id="chunk-1", quote_text="The bell rings")


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
