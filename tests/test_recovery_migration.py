"""Alembic smoke coverage for non-canonical recovery attempt persistence."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from comic_agent.config import get_settings
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
        directive_id="migration-directive",
        idempotency_key="migration-recovery-key",
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
            policy_id="migration-policy",
            allowed_issue_codes=[ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND],
            terminal_issue_codes=[ReviewIssueCode.EXACT_DUPLICATE],
            max_attempts_per_proposal=1,
            max_attempts_per_window=1,
            max_attempts_per_root_run=1,
            max_total_tokens=100,
            max_elapsed_seconds=60,
        ),
        budget_usage=RecoveryBudgetUsageV1(),
    )
    return RecoveryAttemptV1(
        attempt_id="migration-attempt",
        idempotency_key=directive.idempotency_key,
        directive=directive,
        status=RecoveryAttemptStatus.RESERVED,
        original_gate2_issue_codes=directive.issue_codes,
    )


def test_alembic_upgrade_creates_recovery_attempt_audit_table(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration-smoke.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    columns = {
        column["name"]
        for column in inspector.get_columns("narrative_analysis_recovery_attempts")
    }
    assert columns == {
        "attempt_id",
        "root_analysis_run_id",
        "idempotency_key",
        "status",
        "payload",
        "created_at",
        "updated_at",
    }
    unique_constraint_names = {
        item["name"]
        for item in inspector.get_unique_constraints("narrative_analysis_recovery_attempts")
    }
    assert unique_constraint_names >= {
        "uq_recovery_attempt_key"
    }
    assert "ix_narrative_analysis_recovery_attempts_root_analysis_run_id" in {
        item["name"] for item in inspector.get_indexes("narrative_analysis_recovery_attempts")
    }

    first = NarrativeAnalysisRecoveryRepository(Session(engine))
    second = NarrativeAnalysisRecoveryRepository(Session(engine))
    stored, created = first.reserve_attempt(_attempt())
    duplicate, created_again = second.reserve_attempt(_attempt())

    assert created is True
    assert created_again is False
    assert duplicate.attempt_id == stored.attempt_id
    get_settings.cache_clear()
