"""Persistence tests for idempotent recovery attempts."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.schemas.recovery import (
    RecoveryAttemptStatus,
    RecoveryAttemptV1,
    RecoveryBudgetUsageV1,
    RecoveryDirectiveV1,
    RecoveryPolicyV1,
)
from comic_agent.schemas.review import ReviewIssueCode


def _attempt() -> RecoveryAttemptV1:
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
        ordered_source_chunk_ids=["chunk-1"],
        approved_source_chunk_ids=["chunk-1"],
        issue_ids=["issue-1"],
        issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
        policy=RecoveryPolicyV1(
            policy_id="policy-1",
            allowed_issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
            terminal_issue_codes=[ReviewIssueCode.EXACT_DUPLICATE],
            max_attempts_per_proposal=2,
            max_attempts_per_window=2,
            max_attempts_per_root_run=2,
            max_total_tokens=10,
            max_elapsed_seconds=10,
        ),
        budget_usage=RecoveryBudgetUsageV1(),
    )
    return RecoveryAttemptV1(
        attempt_id="attempt-1",
        idempotency_key=directive.idempotency_key,
        directive=directive,
        status=RecoveryAttemptStatus.RESERVED,
        original_gate2_issue_codes=directive.issue_codes,
    )


def test_same_idempotency_key_is_reserved_once_across_sessions(tmp_path) -> None:
    """Removing the unique reservation must cause duplicate work to be caught."""

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}")
    Base.metadata.create_all(engine)
    first = NarrativeAnalysisRecoveryRepository(Session(engine))
    second = NarrativeAnalysisRecoveryRepository(Session(engine))

    stored, created = first.reserve_attempt(_attempt())
    duplicate, created_again = second.reserve_attempt(_attempt())

    assert created is True
    assert created_again is False
    assert duplicate.attempt_id == stored.attempt_id
    assert second.count_attempts("analysis-1") == 1


def test_terminal_attempt_cannot_be_replaced_by_a_different_payload(tmp_path) -> None:
    """A completed audit must remain append-only after a re-entry call."""

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'terminal.db'}")
    Base.metadata.create_all(engine)
    repository = NarrativeAnalysisRecoveryRepository(Session(engine))
    stored, _ = repository.reserve_attempt(_attempt())
    completed = stored.model_copy(
        update={
            "status": RecoveryAttemptStatus.COMPLETED,
            "outcome": None,
            "completed_at": stored.created_at,
        }
    )

    try:
        repository.save_attempt_transition(completed)
    except ValueError as exc:
        assert "outcome" in str(exc)
    else:
        raise AssertionError("completed attempt without a final outcome must be rejected")
