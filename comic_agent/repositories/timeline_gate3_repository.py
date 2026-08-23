"""Database-backed reservation and state claims for Timeline/Gate 3."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import TimelineGate3RunModel
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisInputV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
)

_TERMINAL = {
    TimelineGate3RunStatus.APPROVED,
    TimelineGate3RunStatus.REJECTED,
    TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
    TimelineGate3RunStatus.FAILED,
}


class TimelineGate3Repository:
    """Persistent idempotency; execution claims never rely on an in-memory lock."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_run(self, timeline_run_id: str) -> TimelineGate3RunV1 | None:
        row = self._session.get(TimelineGate3RunModel, timeline_run_id)
        return TimelineGate3RunV1.model_validate(row.payload) if row is not None else None

    def get_by_bundle(self, project_id: str, bundle_id: str) -> TimelineGate3RunV1 | None:
        row = self._session.scalar(
            select(TimelineGate3RunModel).where(
                TimelineGate3RunModel.project_id == project_id,
                TimelineGate3RunModel.source_bundle_id == bundle_id,
            )
        )
        return TimelineGate3RunV1.model_validate(row.payload) if row is not None else None

    def reserve_run(self, run: TimelineGate3RunV1) -> TimelineGate3RunV1:
        """Create once, returning the durable winner after a uniqueness race."""

        # Preserve the existing lookup key for fully-approved Gate 2 runs.  The
        # pipeline status API and legacy recovery paths query by the approved
        # bundle ID; execution-only runs (non-blocking Gate 2 outcomes) have no
        # such bundle and therefore use their execution-bundle ID instead.
        source_bundle_id = (
            run.source_approved_proposal_bundle_id
            or run.source_narrative_execution_bundle_id
        )
        if source_bundle_id is None:
            raise ValueError("Timeline Gate 3 run requires source bundle provenance")
        existing = self.get_by_bundle(run.project_id, source_bundle_id)
        if existing is not None:
            return existing
        try:
            self._session.add(
                TimelineGate3RunModel(
                    timeline_run_id=run.timeline_run_id,
                    project_id=run.project_id,
                    source_bundle_id=source_bundle_id,
                    idempotency_key=run.idempotency_key,
                    status=str(run.status),
                    payload=run.model_dump(mode="json"),
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            self._session.commit()
            return run
        except IntegrityError:
            self._session.rollback()
            existing = self.get_by_bundle(run.project_id, source_bundle_id)
            if existing is None:
                raise
            return existing

    def claim_provider(
        self, run: TimelineGate3RunV1, timeline_input: TimelineAnalysisInputV1
    ) -> bool:
        """Atomically move RESERVED to RUNNING; exactly one caller may invoke Provider."""

        updated = run.model_copy(
            update={
                "status": TimelineGate3RunStatus.RUNNING,
                "timeline_input": timeline_input,
                "updated_at": datetime.now(UTC),
            }
        )
        result = self._session.execute(
            update(TimelineGate3RunModel)
            .where(
                TimelineGate3RunModel.timeline_run_id == run.timeline_run_id,
                TimelineGate3RunModel.status == str(TimelineGate3RunStatus.RESERVED),
            )
            .values(
                status=str(TimelineGate3RunStatus.RUNNING),
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1

    def claim_review(self, run: TimelineGate3RunV1) -> bool:
        """Atomically move a successful Provider checkpoint into Gate 3 review."""

        updated = run.model_copy(
            update={
                "status": TimelineGate3RunStatus.REVIEWING,
                "updated_at": datetime.now(UTC),
            }
        )
        result = self._session.execute(
            update(TimelineGate3RunModel)
            .where(
                TimelineGate3RunModel.timeline_run_id == run.timeline_run_id,
                TimelineGate3RunModel.status == str(TimelineGate3RunStatus.PROVIDER_SUCCEEDED),
            )
            .values(
                status=str(TimelineGate3RunStatus.REVIEWING),
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1

    def claim_recovery(self, run: TimelineGate3RunV1) -> bool:
        """Atomically claim the single budgeted recovery slot after a rejection."""

        budget = run.recovery_budget.model_copy(
            update={"attempts_used": run.recovery_budget.attempts_used + 1}
        )
        updated = run.model_copy(
            update={
                "status": TimelineGate3RunStatus.RECOVERY_RUNNING,
                "recovery_budget": budget,
                "initial_timeline_proposal": run.timeline_proposal,
                "initial_gate3_result": run.gate3_result,
                "initial_gate3_route": run.gate3_route,
                "initial_timeline_review_material": run.timeline_review_material,
                "updated_at": datetime.now(UTC),
            }
        )
        result = self._session.execute(
            update(TimelineGate3RunModel)
            .where(
                TimelineGate3RunModel.timeline_run_id == run.timeline_run_id,
                TimelineGate3RunModel.status == TimelineGate3RunStatus.REJECTED,
            )
            .values(
                status=str(TimelineGate3RunStatus.RECOVERY_RUNNING),
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1

    def save_transition(self, run: TimelineGate3RunV1) -> TimelineGate3RunV1:
        """Persist a checkpoint while refusing to overwrite a terminal outcome."""

        row = self._session.get(TimelineGate3RunModel, run.timeline_run_id)
        if row is None:
            raise ValueError(f"Timeline Gate 3 run not found: {run.timeline_run_id}")
        previous = TimelineGate3RunV1.model_validate(row.payload)
        recovery_promotes_rejected = (
            previous.status == TimelineGate3RunStatus.REJECTED
            and run.status in {
                TimelineGate3RunStatus.RECOVERY_RUNNING,
                TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
                TimelineGate3RunStatus.REVIEWING,
                TimelineGate3RunStatus.APPROVED,
                TimelineGate3RunStatus.REJECTED,
                TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
                TimelineGate3RunStatus.FAILED,
            }
            and run.initial_gate3_result is not None
        )
        if (
            previous.status in _TERMINAL
            and previous.status != run.status
            and not recovery_promotes_rejected
        ):
            return previous
        row.status = str(run.status)
        row.payload = run.model_dump(mode="json")
        row.updated_at = run.updated_at
        self._session.commit()
        return run

    def apply_human_review(self, run: TimelineGate3RunV1) -> bool:
        """Atomically resolve exactly one held Gate 3 run through explicit human review."""

        if run.status not in {
            TimelineGate3RunStatus.APPROVED,
            TimelineGate3RunStatus.REJECTED,
        }:
            raise ValueError("Human review must resolve Gate 3 to APPROVED or REJECTED")
        if (
            run.gate3_result is None
            or run.gate3_result.human_review is None
            or run.gate3_result.effective_decision != str(run.status)
        ):
            raise ValueError("Human review metadata must match the resolved Gate 3 status")
        result = self._session.execute(
            update(TimelineGate3RunModel)
            .where(
                TimelineGate3RunModel.timeline_run_id == run.timeline_run_id,
                TimelineGate3RunModel.status
                == str(TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW),
            )
            .values(
                status=str(run.status),
                payload=run.model_dump(mode="json"),
                updated_at=run.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1

    def finalize_human_approval(self, run: TimelineGate3RunV1) -> bool:
        """Persist a missing canonical bundle for an already human-approved run."""

        if (
            run.status != TimelineGate3RunStatus.APPROVED
            or run.approved_timeline_bundle is None
            or run.gate3_result is None
            or run.gate3_result.human_review is None
            or run.gate3_result.effective_decision != str(ReviewGate3Decision.APPROVED)
        ):
            raise ValueError("Only a human-approved Gate 3 run can be finalized")
        result = self._session.execute(
            update(TimelineGate3RunModel)
            .where(
                TimelineGate3RunModel.timeline_run_id == run.timeline_run_id,
                TimelineGate3RunModel.status == str(TimelineGate3RunStatus.APPROVED),
            )
            .values(
                payload=run.model_dump(mode="json"),
                updated_at=run.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1
