"""Contracts for bounded, original-window recovery attempts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comic_agent.schemas.recovery import (
    RecoveryAttemptStatus,
    RecoveryAttemptV1,
    RecoveryBudgetUsageV1,
    RecoveryDirectiveV1,
    RecoveryOutcomeStatus,
    RecoveryPolicyV1,
)
from comic_agent.schemas.review import ReviewIssueCode
from comic_agent.schemas.workflow import NarrativeAnalysisRunV1


def _policy(**updates: object) -> RecoveryPolicyV1:
    payload: dict[str, object] = {
        "policy_id": "recovery-policy-v1",
        "allowed_issue_codes": [ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
        "terminal_issue_codes": [ReviewIssueCode.EXACT_DUPLICATE],
        "max_attempts_per_proposal": 2,
        "max_attempts_per_window": 2,
        "max_attempts_per_root_run": 3,
        "max_total_tokens": 100,
        "max_elapsed_seconds": 60,
        "max_provider_requests": 3,
    }
    return RecoveryPolicyV1(
        **(payload | updates),
    )


def test_recovery_policy_rejects_empty_or_overlapping_issue_classifications() -> None:
    """A policy cannot silently recover an unspecified or terminal issue."""

    with pytest.raises(ValidationError, match="allowed_issue_codes"):
        _policy(allowed_issue_codes=[])
    with pytest.raises(ValidationError, match="disjoint"):
        _policy(terminal_issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND])


def test_recovery_directive_locks_ordered_original_scope_and_policy_snapshot() -> None:
    """Changing a window order or approval scope invalidates its rerun directive."""

    directive = RecoveryDirectiveV1(
        directive_id="directive-1",
        idempotency_key="recovery-key-1",
        root_analysis_run_id="analysis-1",
        project_id="project-1",
        document_id="document-1",
        proposal_id="proposal-1",
        proposal_schema="EventProposalV1",
        mode="event_extraction",
        original_window_id="window-1",
        original_agent_run_id="agent-run-1",
        ordered_source_chunk_ids=["chunk-1", "chunk-2"],
        approved_source_chunk_ids=["chunk-1", "chunk-2"],
        issue_ids=["issue-1"],
        issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
        policy=_policy(),
        budget_usage=RecoveryBudgetUsageV1(),
        created_at=datetime.now(UTC),
    )

    assert directive.ordered_source_chunk_ids == ["chunk-1", "chunk-2"]
    assert directive.policy.policy_id == "recovery-policy-v1"
    with pytest.raises(ValidationError, match="approved_source_chunk_ids"):
        directive.model_copy(
            update={"approved_source_chunk_ids": ["chunk-2", "chunk-1"]}
        ).model_validate(
            directive.model_copy(
                update={"approved_source_chunk_ids": ["chunk-2", "chunk-1"]}
            ).model_dump(mode="json")
        )


def test_legacy_analysis_run_payload_defaults_recovery_outcomes_to_empty() -> None:
    """Adding recovery history must not make v1.0/v1.1 persisted runs unreadable."""

    legacy = NarrativeAnalysisRunV1.model_validate(
        {
            "schema_version": "1.1",
            "analysis_run_id": "analysis-1",
            "project_id": "project-1",
            "document_id": "document-1",
            "modes": ["event_extraction"],
            "status": "SUCCEEDED",
        }
    )

    assert legacy.recovery_outcomes == []
    assert RecoveryAttemptStatus.RESERVED == "RESERVED"
    assert RecoveryAttemptStatus.PROVIDER_SUCCEEDED == "PROVIDER_SUCCEEDED"
    assert RecoveryOutcomeStatus.BUDGET_EXHAUSTED == "BUDGET_EXHAUSTED"


def test_provider_succeeded_requires_persisted_new_agent_provenance() -> None:
    directive = RecoveryDirectiveV1(
        directive_id="directive-2", idempotency_key="key-2", root_analysis_run_id="analysis-1",
        project_id="project-1", document_id="document-1", proposal_id="proposal-1",
        proposal_schema="EventProposalV1", mode="event_extraction", original_window_id="window-1",
        original_agent_run_id="agent-run-1", ordered_source_chunk_ids=["chunk-1"],
        approved_source_chunk_ids=["chunk-1"], issue_ids=["issue-1"],
        issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND], policy=_policy(),
        budget_usage=RecoveryBudgetUsageV1(),
    )

    with pytest.raises(ValidationError, match="new AgentRun provenance"):
        RecoveryAttemptV1(
            attempt_id="attempt-2", idempotency_key="key-2", directive=directive,
            status=RecoveryAttemptStatus.PROVIDER_SUCCEEDED,
            original_gate2_issue_codes=directive.issue_codes,
        )
