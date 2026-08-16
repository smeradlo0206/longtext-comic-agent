"""Atomic append-only persistence for Stage B recovery attempts."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import NarrativeAnalysisRecoveryAttemptModel
from comic_agent.schemas.recovery import RecoveryAttemptStatus, RecoveryAttemptV1


class NarrativeAnalysisRecoveryRepository:
    """Reserve each logical rerun once before any Provider invocation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def reserve_attempt(self, attempt: RecoveryAttemptV1) -> tuple[RecoveryAttemptV1, bool]:
        """Create one durable RESERVED attempt or return its existing peer."""

        existing = self._by_key(attempt.idempotency_key)
        if existing is not None:
            return existing, False
        now = datetime.now(UTC)
        self._session.add(
            NarrativeAnalysisRecoveryAttemptModel(
                attempt_id=attempt.attempt_id,
                root_analysis_run_id=attempt.directive.root_analysis_run_id,
                idempotency_key=attempt.idempotency_key,
                status=str(attempt.status),
                payload=attempt.model_dump(mode="json"),
                created_at=attempt.created_at,
                updated_at=now,
            )
        )
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._by_key(attempt.idempotency_key)
            if existing is None:
                raise
            return existing, False
        return attempt, True

    def get_attempt(self, attempt_id: str) -> RecoveryAttemptV1 | None:
        row = self._session.get(NarrativeAnalysisRecoveryAttemptModel, attempt_id)
        return RecoveryAttemptV1.model_validate(row.payload) if row is not None else None

    def list_attempts(self, root_analysis_run_id: str) -> list[RecoveryAttemptV1]:
        rows = self._session.scalars(
            select(NarrativeAnalysisRecoveryAttemptModel)
            .where(
                NarrativeAnalysisRecoveryAttemptModel.root_analysis_run_id == root_analysis_run_id
            )
            .order_by(NarrativeAnalysisRecoveryAttemptModel.created_at)
        ).all()
        return [RecoveryAttemptV1.model_validate(row.payload) for row in rows]

    def count_attempts(self, root_analysis_run_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(NarrativeAnalysisRecoveryAttemptModel)
                .where(
                    NarrativeAnalysisRecoveryAttemptModel.root_analysis_run_id
                    == root_analysis_run_id
                )
            )
            or 0
        )

    def save_attempt_transition(self, attempt: RecoveryAttemptV1) -> RecoveryAttemptV1:
        """Persist only monotonic, nonterminal state transitions."""

        attempt = RecoveryAttemptV1.model_validate(attempt.model_dump(mode="json"))
        row = self._session.get(NarrativeAnalysisRecoveryAttemptModel, attempt.attempt_id)
        if row is None:
            raise ValueError(f"RecoveryAttempt not found: {attempt.attempt_id}")
        current = RecoveryAttemptV1.model_validate(row.payload)
        if current.status == RecoveryAttemptStatus.COMPLETED:
            if current.model_dump(mode="json") != attempt.model_dump(mode="json"):
                raise ValueError("terminal recovery attempt cannot be overwritten")
            return current
        allowed = {
            RecoveryAttemptStatus.RESERVED: {RecoveryAttemptStatus.RUNNING},
            RecoveryAttemptStatus.RUNNING: {
                RecoveryAttemptStatus.PROVIDER_SUCCEEDED,
                RecoveryAttemptStatus.REVIEWING,
            },
            RecoveryAttemptStatus.PROVIDER_SUCCEEDED: {RecoveryAttemptStatus.REVIEWING},
            RecoveryAttemptStatus.REVIEWING: {RecoveryAttemptStatus.COMPLETED},
        }
        if attempt.status not in allowed.get(current.status, set()):
            raise ValueError("invalid recovery attempt transition")
        row.status = str(attempt.status)
        row.payload = attempt.model_dump(mode="json")
        row.updated_at = datetime.now(UTC)
        self._session.commit()
        return attempt

    def _by_key(self, idempotency_key: str) -> RecoveryAttemptV1 | None:
        row = self._session.scalar(
            select(NarrativeAnalysisRecoveryAttemptModel).where(
                NarrativeAnalysisRecoveryAttemptModel.idempotency_key == idempotency_key
            )
        )
        return RecoveryAttemptV1.model_validate(row.payload) if row is not None else None
