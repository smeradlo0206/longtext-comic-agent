"""Review Gate 2 v1.0 contract tests."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    EvidenceReviewItemV1,
    ProposalReviewDecisionV1,
    ReferenceResolutionDecisionV1,
    ReferenceTargetCandidateV1,
    ReviewableProposalEnvelopeV1,
    ReviewGate2InputV1,
    ReviewGate2PolicyV1,
    ReviewGate2ResultV1,
    ReviewIssueV1,
)


def _evidence(chunk_id: str = "chunk-1", quote: str = "source evidence") -> dict[str, object]:
    return {"chunk_id": chunk_id, "quote_text": quote}


def _issue(
    issue_id: str = "issue-1",
    *,
    category: str = "EVIDENCE",
    severity: str = "BLOCKING",
) -> dict[str, object]:
    return {
        "issue_id": issue_id,
        "code": "EVIDENCE_QUOTE_NOT_FOUND",
        "category": category,
        "severity": severity,
        "sanitized_message": "safe audit message",
    }


def _event(proposal_id: str = "event-1") -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "event_type": "DISCOVERY",
        "summary": "A discovery occurs.",
        "evidence_refs": [_evidence()],
        "confidence": 0.9,
        "reality_layer": "PRIMARY",
    }


def _entity(proposal_id: str = "entity-1") -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "entity_type": "CHARACTER",
        "canonical_name": "Lin",
        "evidence_refs": [_evidence()],
        "confidence": 0.9,
    }


def _claim(proposal_id: str = "claim-1") -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "claim_type": "FACTUAL_ASSERTION",
        "claim_text": "The gate is closed.",
        "temporal_scope": "PRESENT",
        "source_type": "NARRATOR",
        "verification_status": "UNVERIFIED",
        "evidence_refs": [_evidence()],
        "confidence": 0.9,
        "reality_layer": "PRIMARY",
    }


def _knowledge(proposal_id: str = "knowledge-1") -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "subject": {
            "mention_text": "Lin",
            "entity_proposal_id": None,
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "target_text": "The gate is closed.",
            "target_kind": "WORLD_FACT",
            "proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "epistemic_status": "SUSPECTS",
        "epistemic_basis": "UNKNOWN",
        "reality_layer": "PRIMARY",
        "evidence_refs": [_evidence()],
        "confidence": 0.9,
    }


def _state_change(proposal_id: str = "state-change-1") -> dict[str, object]:
    return {
        "proposal_id": proposal_id,
        "event": {
            "event_summary": "Lin is injured.",
            "event_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "mention_text": "Lin",
            "target_kind": "CHARACTER",
            "entity_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "attribute_path": "health.injury",
        "old_value": None,
        "new_value": "injured",
        "persistent": False,
        "reality_layer": "PRIMARY",
        "evidence_refs": [_evidence()],
        "new_value_evidence_indexes": [0],
        "persistence_evidence_indexes": [],
        "confidence": 0.9,
    }


def _relationship(proposal_id: str = "relationship-1") -> dict[str, object]:
    def participant(text: str) -> dict[str, object]:
        return {
            "mention_text": text,
            "participant_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": None,
        }

    return {
        "proposal_id": proposal_id,
        "subject": participant("Lin"),
        "counterpart": participant("Lan"),
        "relationship_domain": "TRUST",
        "relationship_kind": "TRUSTS",
        "directionality": "DIRECTED",
        "signal_effect": "PRESENT",
        "assertion_polarity": "AFFIRMED",
        "evidence_basis": "NARRATED",
        "support_level": "EXPLICIT",
        "temporal_anchor": {
            "valid_from": None,
            "valid_until": None,
            "anchor_text": None,
            "resolution_status": "UNRESOLVED",
            "event_proposal_id": None,
            "proposal_schema": None,
        },
        "reality_layer": "PRIMARY",
        "evidence_refs": [_evidence()],
        "confidence": 0.9,
    }


_PROPOSALS: dict[str, tuple[str, dict[str, object]]] = {
    "event_extraction": ("EventProposalV1", _event()),
    "entity_extraction": ("EntityProposalV1", _entity()),
    "claim_extraction": ("ClaimProposalV1", _claim()),
    "knowledge_state_extraction": ("KnowledgeStateProposalV1", _knowledge()),
    "state_change_extraction": ("StateChangeProposalV1", _state_change()),
    "relationship_signal_extraction": ("RelationshipSignalProposalV1", _relationship()),
}


def _envelope(mode: str = "event_extraction", proposal_id: str | None = None) -> dict[str, object]:
    schema, proposal = _PROPOSALS[mode]
    proposal = deepcopy(proposal)
    if proposal_id is not None:
        proposal["proposal_id"] = proposal_id
    return {
        "mode": mode,
        "proposal_schema": schema,
        "proposal": proposal,
        "agent_run_ids": ["agent-run-1"],
        "aggregated_evidence_refs": [_evidence()],
    }


def _reference(status: str = "RESOLVED", *, required: bool = True) -> dict[str, object]:
    item: dict[str, object] = {
        "reference_path": "target.entity",
        "mention_text": "Lin",
        "expected_target_schemas": ["EntityProposalV1"],
        "required_for_downstream": required,
        "status": status,
        "candidates": [],
        "selected_target_proposal_id": None,
        "selected_target_proposal_schema": None,
        "resolution_basis": "NONE",
        "issues": [],
    }
    if status == "RESOLVED":
        item.update(
            candidates=[
                {
                    "target_proposal_id": "entity-1",
                    "target_proposal_schema": "EntityProposalV1",
                    "match_basis": "EXPLICIT_PROPOSAL_ID",
                }
            ],
            selected_target_proposal_id="entity-1",
            selected_target_proposal_schema="EntityProposalV1",
            resolution_basis="EXPLICIT_PROPOSAL_ID",
        )
    elif status == "AMBIGUOUS":
        item["candidates"] = [
            {
                "target_proposal_id": "entity-1",
                "target_proposal_schema": "EntityProposalV1",
                "match_basis": "EXPLICIT_PROPOSAL_ID",
            },
            {
                "target_proposal_id": "entity-2",
                "target_proposal_schema": "EntityProposalV1",
                "match_basis": "EXACT_UNIQUE_MENTION",
            },
        ]
        item["issues"] = [_issue("ambiguous", category="REFERENCE", severity="REVIEW_REQUIRED")]
    elif status == "UNRESOLVED" and required:
        item["issues"] = [_issue("unresolved", category="REFERENCE", severity="REVIEW_REQUIRED")]
    elif status == "REJECTED":
        item["issues"] = [_issue("rejected", category="REFERENCE", severity="BLOCKING")]
    return item


def _decision(decision: str = "APPROVED", *, proposal_id: str = "event-1") -> dict[str, object]:
    item: dict[str, object] = {
        "decision_id": "decision-1",
        "analysis_run_id": "analysis-1",
        "proposal_id": proposal_id,
        "proposal_schema": "EventProposalV1",
        "mode": "event_extraction",
        "decision": decision,
        "schema_status": "PASSED",
        "provenance_status": "PASSED",
        "evidence_status": "PASSED",
        "mode_boundary_status": "PASSED",
        "evidence_reviews": [
            {"evidence_index": 0, "evidence_ref": _evidence(), "status": "PASSED"}
        ],
        "reference_decisions": [_reference()],
        "issues": [],
        "review_method": "DETERMINISTIC",
        "reviewed_by": "review-gate-2",
    }
    if decision == "REJECTED":
        item["schema_status"] = "FAILED"
        item["issues"] = [_issue()]
    elif decision == "NEEDS_HUMAN_REVIEW":
        item["schema_status"] = "NEEDS_HUMAN_REVIEW"
        item["issues"] = [_issue("pending", category="REFERENCE", severity="REVIEW_REQUIRED")]
    return item


def test_review_gate_policy_is_a_fixed_safe_snapshot() -> None:
    policy = ReviewGate2PolicyV1(policy_id="review-policy-1")

    assert policy.require_evidence is True
    assert policy.exact_reference_matching_only is True
    assert policy.allow_fuzzy_reference_matching is False
    assert policy.allow_llm_reference_resolution is False
    assert policy.allow_canonical_writes is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("issue_id", "  "),
        ("sanitized_message", "  "),
        ("field_path", "  "),
        ("related_object_ids", ["proposal-1", "proposal-1"]),
        ("evidence_index", -1),
    ],
)
def test_review_issue_rejects_invalid_audit_metadata(field: str, value: object) -> None:
    issue = _issue() | {field: value}

    with pytest.raises(ValidationError):
        ReviewIssueV1.model_validate(issue)


@pytest.mark.parametrize("mode", list(_PROPOSALS))
def test_each_narrative_proposal_type_has_a_valid_review_envelope(mode: str) -> None:
    envelope = ReviewableProposalEnvelopeV1.model_validate(_envelope(mode))

    assert envelope.mode == mode
    assert envelope.proposal.proposal_id


def test_envelope_rejects_mismatched_mode_schema_and_repeated_agent_run() -> None:
    mismatched = _envelope() | {"mode": "claim_extraction"}
    with pytest.raises(ValidationError, match="mode"):
        ReviewableProposalEnvelopeV1.model_validate(mismatched)
    with pytest.raises(ValidationError, match="unique"):
        ReviewableProposalEnvelopeV1.model_validate(_envelope() | {"agent_run_ids": ["run", "run"]})


def test_review_input_allows_empty_proposals_and_rejects_duplicate_keys() -> None:
    empty = ReviewGate2InputV1(
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )
    assert empty.proposals == []
    with pytest.raises(ValidationError, match="unique proposal"):
        ReviewGate2InputV1.model_validate(
            empty.model_dump() | {"proposals": [_envelope(), _envelope()]}
        )


def test_evidence_review_cross_validation() -> None:
    passed = EvidenceReviewItemV1(evidence_index=0, evidence_ref=_evidence(), status="PASSED")
    assert passed.status == "PASSED"
    with pytest.raises(ValidationError, match="BLOCKING"):
        EvidenceReviewItemV1(evidence_index=0, evidence_ref=_evidence(), status="FAILED")
    with pytest.raises(ValidationError, match="PASSED"):
        EvidenceReviewItemV1(
            evidence_index=0, evidence_ref=_evidence(), status="PASSED", issues=[_issue()]
        )


def test_reference_decision_all_four_statuses_and_rejections() -> None:
    assert ReferenceResolutionDecisionV1.model_validate(_reference()).status == "RESOLVED"
    assert (
        ReferenceResolutionDecisionV1.model_validate(
            _reference("UNRESOLVED", required=False)
        ).status
        == "UNRESOLVED"
    )
    assert (
        ReferenceResolutionDecisionV1.model_validate(_reference("AMBIGUOUS")).status == "AMBIGUOUS"
    )
    assert ReferenceResolutionDecisionV1.model_validate(_reference("REJECTED")).status == "REJECTED"
    for invalid in (
        _reference() | {"selected_target_proposal_id": None},
        _reference() | {"selected_target_proposal_schema": "ClaimProposalV1"},
        _reference() | {"candidates": []},
        _reference("UNRESOLVED") | {"issues": []},
        _reference("AMBIGUOUS") | {"candidates": [_reference()["candidates"][0]]},
        _reference("AMBIGUOUS") | {"selected_target_proposal_id": "entity-1"},
        _reference("REJECTED") | {"issues": []},
    ):
        with pytest.raises(ValidationError):
            ReferenceResolutionDecisionV1.model_validate(invalid)


@pytest.mark.parametrize(
    "candidate",
    [
        {
            "target_proposal_id": "  ",
            "target_proposal_schema": "EntityProposalV1",
            "match_basis": "EXPLICIT_PROPOSAL_ID",
        },
        {
            "target_proposal_id": "entity-1",
            "target_proposal_schema": "EntityProposalV1",
            "match_basis": "NONE",
        },
        {
            "target_proposal_id": "entity-1",
            "target_proposal_schema": "EntityProposalV1",
            "match_basis": "EXACT_UNIQUE_MENTION",
            "source_mention": "  ",
        },
    ],
)
def test_reference_candidate_rejects_invalid_exact_matching_metadata(
    candidate: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ReferenceTargetCandidateV1.model_validate(candidate)


def test_reference_decision_rejects_duplicate_candidates_and_expected_schemas() -> None:
    resolved = _reference()
    resolved["candidates"] = resolved["candidates"] * 2
    with pytest.raises(ValidationError, match="unique"):
        ReferenceResolutionDecisionV1.model_validate(resolved)
    duplicate_schema = _reference() | {
        "expected_target_schemas": ["EntityProposalV1", "EntityProposalV1"]
    }
    with pytest.raises(ValidationError, match="unique"):
        ReferenceResolutionDecisionV1.model_validate(duplicate_schema)


def test_decision_cross_validation_for_all_decisions_and_methods() -> None:
    assert ProposalReviewDecisionV1.model_validate(_decision()).decision == "APPROVED"
    assert ProposalReviewDecisionV1.model_validate(_decision("REJECTED")).decision == "REJECTED"
    assert (
        ProposalReviewDecisionV1.model_validate(_decision("NEEDS_HUMAN_REVIEW")).decision
        == "NEEDS_HUMAN_REVIEW"
    )
    invalid_approved = _decision() | {"evidence_status": "FAILED"}
    invalid_required_reference = _decision() | {"reference_decisions": [_reference("AMBIGUOUS")]}
    invalid_rejected = _decision("REJECTED") | {"issues": []}
    invalid_pending = _decision("NEEDS_HUMAN_REVIEW") | {"schema_status": "PASSED", "issues": []}
    for invalid in (
        invalid_approved,
        invalid_required_reference,
        invalid_rejected,
        invalid_pending,
    ):
        with pytest.raises(ValidationError):
            ProposalReviewDecisionV1.model_validate(invalid)
    with pytest.raises(ValidationError, match="HUMAN"):
        ProposalReviewDecisionV1.model_validate(_decision() | {"review_method": "HUMAN"})
    with pytest.raises(ValidationError, match="DETERMINISTIC"):
        ProposalReviewDecisionV1.model_validate(_decision() | {"supersedes_decision_id": "old"})


def test_decision_rejects_duplicate_evidence_references_and_issue_paths() -> None:
    duplicate_evidence = _decision() | {
        "evidence_reviews": [
            {"evidence_index": 0, "evidence_ref": _evidence(), "status": "PASSED"},
            {"evidence_index": 0, "evidence_ref": _evidence(), "status": "PASSED"},
        ]
    }
    duplicate_paths = _decision() | {"reference_decisions": [_reference(), _reference()]}
    duplicate_issues = _decision("REJECTED") | {"issues": [_issue(), _issue()]}
    for invalid in (duplicate_evidence, duplicate_paths, duplicate_issues):
        with pytest.raises(ValidationError, match="unique"):
            ProposalReviewDecisionV1.model_validate(invalid)


def _bundle() -> dict[str, object]:
    return {
        "bundle_id": "bundle-1",
        "project_id": "project-1",
        "document_id": "document-1",
        "analysis_run_id": "analysis-1",
        "review_run_id": "review-1",
        "policy_id": "policy-1",
        "approved_proposals": [{"source": _envelope(), "review_decision_id": "decision-1"}],
        "review_decision_ids": ["decision-1"],
    }


def _result(status: str = "COMPLETED") -> dict[str, object]:
    decisions = [_decision()]
    bundle: dict[str, object] | None = _bundle()
    if status == "NEEDS_HUMAN_REVIEW":
        decisions = [_decision("NEEDS_HUMAN_REVIEW")]
        bundle = None
    if status == "FAILED":
        decisions = []
        bundle = None
    return {
        "review_run_id": "review-1",
        "project_id": "project-1",
        "document_id": "document-1",
        "analysis_run_id": "analysis-1",
        "status": status,
        "policy": {"policy_id": "policy-1"},
        "decisions": decisions,
        "total_count": len(decisions),
        "approved_count": sum(item["decision"] == "APPROVED" for item in decisions),
        "rejected_count": sum(item["decision"] == "REJECTED" for item in decisions),
        "needs_human_review_count": sum(
            item["decision"] == "NEEDS_HUMAN_REVIEW" for item in decisions
        ),
        "approved_bundle": bundle,
        "execution_issues": [_issue("execution", category="EXECUTION", severity="BLOCKING")]
        if status == "FAILED"
        else [],
    }


def test_result_bundle_alignment_and_empty_completed_bundles() -> None:
    completed = ReviewGate2ResultV1.model_validate(_result())
    assert completed.approved_bundle is not None
    rejected = _result()
    rejected["decisions"] = [_decision("REJECTED")]
    rejected.update(
        total_count=1,
        approved_count=0,
        rejected_count=1,
        approved_bundle=_bundle() | {"approved_proposals": [], "review_decision_ids": []},
    )
    assert ReviewGate2ResultV1.model_validate(rejected).approved_count == 0
    no_proposals = _result() | {
        "decisions": [],
        "total_count": 0,
        "approved_count": 0,
        "approved_bundle": _bundle() | {"approved_proposals": [], "review_decision_ids": []},
    }
    assert ReviewGate2ResultV1.model_validate(no_proposals).total_count == 0
    for invalid in (
        _result() | {"needs_human_review_count": 1},
        _result() | {"status": "NEEDS_HUMAN_REVIEW"},
        _result("FAILED") | {"execution_issues": []},
        _result() | {"approved_bundle": _bundle() | {"analysis_run_id": "other"}},
        _result()
        | {"approved_bundle": _bundle() | {"approved_proposals": [], "review_decision_ids": []}},
    ):
        with pytest.raises(ValidationError):
            ReviewGate2ResultV1.model_validate(invalid)


def test_approved_bundle_rejects_duplicate_items_and_blocking_references() -> None:
    duplicate_items = _bundle() | {
        "approved_proposals": _bundle()["approved_proposals"] * 2,
        "review_decision_ids": ["decision-1", "decision-2"],
    }
    with pytest.raises(ValidationError, match="unique"):
        ApprovedProposalBundleV1.model_validate(duplicate_items)
    blocking_reference = _bundle() | {
        "unresolved_nonblocking_references": [_reference("UNRESOLVED")]
    }
    with pytest.raises(ValidationError, match="nonblocking"):
        ApprovedProposalBundleV1.model_validate(blocking_reference)


def test_result_rejects_duplicate_decisions_and_count_mismatch() -> None:
    duplicate_decisions = _result() | {"decisions": [_decision(), _decision()]}
    count_mismatch = _result() | {"total_count": 2}
    for invalid in (duplicate_decisions, count_mismatch):
        with pytest.raises(ValidationError):
            ReviewGate2ResultV1.model_validate(invalid)
