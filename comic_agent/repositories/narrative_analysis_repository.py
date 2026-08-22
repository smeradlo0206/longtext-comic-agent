"""Persistence for resumable whole-document narrative analysis tasks."""

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import NarrativeAnalysisRunModel, NarrativeAnalysisWindowModel
from comic_agent.schemas.review import NarrativeAnalysisReviewRouteV1, ReviewGate2ResultV1
from comic_agent.schemas.workflow import (
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
    NarrativeGate2HandoffStatus,
    NarrativeGate2HandoffV1,
)


class NarrativeAnalysisRepository:
    """Data access layer for analysis parent and window audit records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        run: NarrativeAnalysisRunV1,
        windows: list[NarrativeAnalysisWindowV1],
    ) -> NarrativeAnalysisRunV1:
        """Create a run and its windows idempotently."""

        existing = self._session.get(NarrativeAnalysisRunModel, run.analysis_run_id)
        payload = run.model_dump(mode="json")
        if existing is None:
            self._session.add(
                NarrativeAnalysisRunModel(
                    analysis_run_id=run.analysis_run_id,
                    project_id=run.project_id,
                    document_id=run.document_id,
                    status=str(run.status),
                    payload=payload,
                    result_payload=None,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
        elif existing.payload != payload:
            raise ValueError(f"NarrativeAnalysisRun conflict for id: {run.analysis_run_id}")

        for window in windows:
            self._create_window(window)
        self._session.commit()
        return run

    def get_run(self, analysis_run_id: str) -> NarrativeAnalysisRunV1 | None:
        """Return one persistent analysis run."""

        row = self._session.get(NarrativeAnalysisRunModel, analysis_run_id)
        return NarrativeAnalysisRunV1.model_validate(row.payload) if row is not None else None

    def list_windows(self, analysis_run_id: str) -> list[NarrativeAnalysisWindowV1]:
        """Return mode-window audit records in deterministic order."""

        rows = self._session.scalars(
            select(NarrativeAnalysisWindowModel)
            .where(NarrativeAnalysisWindowModel.analysis_run_id == analysis_run_id)
            .order_by(NarrativeAnalysisWindowModel.mode, NarrativeAnalysisWindowModel.window_index)
        ).all()
        return [NarrativeAnalysisWindowV1.model_validate(row.payload) for row in rows]

    def save_run(self, run: NarrativeAnalysisRunV1) -> NarrativeAnalysisRunV1:
        """Persist mutable run status after a worker state transition."""

        row = self._session.get(NarrativeAnalysisRunModel, run.analysis_run_id)
        if row is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {run.analysis_run_id}")
        row.status = str(run.status)
        row.payload = run.model_dump(mode="json")
        row.updated_at = run.updated_at
        self._session.commit()
        return run

    def save_window(self, window: NarrativeAnalysisWindowV1) -> NarrativeAnalysisWindowV1:
        """Persist one window status without touching sibling windows."""

        row = self._session.get(NarrativeAnalysisWindowModel, window.analysis_window_id)
        if row is None:
            raise ValueError(f"NarrativeAnalysisWindow not found: {window.analysis_window_id}")
        row.status = str(window.status)
        row.agent_run_id = window.agent_run_id
        row.payload = window.model_dump(mode="json")
        row.updated_at = datetime.now(UTC)
        self._session.commit()
        return window

    def claim_window(self, window: NarrativeAnalysisWindowV1) -> bool:
        """Atomically claim one eligible window before any Provider invocation."""

        result = cast(
            CursorResult[Any],
            self._session.execute(
            update(NarrativeAnalysisWindowModel)
            .where(
                NarrativeAnalysisWindowModel.analysis_window_id == window.analysis_window_id,
                NarrativeAnalysisWindowModel.status.in_(
                    [
                        str(NarrativeAnalysisWindowStatus.PENDING),
                        str(NarrativeAnalysisWindowStatus.FAILED),
                    ]
                ),
            )
            .values(
                status=str(window.status),
                agent_run_id=window.agent_run_id,
                payload=window.model_dump(mode="json"),
                updated_at=datetime.now(UTC),
            )
            ),
        )
        self._session.commit()
        return bool(result.rowcount)

    def reserve_root_provider_request(
        self, analysis_run_id: str
    ) -> NarrativeAnalysisRunV1 | None:
        """Atomically reserve one root Provider-call budget slot before invocation.

        Historical runs with a zero cap remain readable and keep their legacy
        behaviour. New planned runs use the optimistic budget version so two
        worker sessions cannot both consume the final slot.
        """

        row = self._session.get(NarrativeAnalysisRunModel, analysis_run_id)
        if row is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {analysis_run_id}")
        current = NarrativeAnalysisRunV1.model_validate(row.payload)
        if (
            current.max_provider_requests > 0
            and current.provider_requests_used >= current.max_provider_requests
        ):
            return None
        now = datetime.now(UTC)
        reserved = current.model_copy(
            update={
                "schema_version": "1.4",
                "provider_requests_used": current.provider_requests_used + 1,
                "execution_budget_version": current.execution_budget_version + 1,
                "updated_at": now,
            }
        )
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(NarrativeAnalysisRunModel)
                .where(
                    NarrativeAnalysisRunModel.analysis_run_id == analysis_run_id,
                    NarrativeAnalysisRunModel.updated_at == row.updated_at,
                )
                .values(
                    status=str(reserved.status),
                    payload=reserved.model_dump(mode="json"),
                    updated_at=now,
                )
            ),
        )
        self._session.commit()
        return reserved if result.rowcount else None

    def create_windows(self, windows: list[NarrativeAnalysisWindowV1]) -> None:
        """Create deterministic recovery windows idempotently."""

        for window in windows:
            self._create_window(window)
        self._session.commit()

    def save_result(self, result: NarrativeAnalysisResultV1) -> NarrativeAnalysisResultV1:
        """Persist the typed, sanitized aggregate result for one task."""

        row = self._session.get(NarrativeAnalysisRunModel, result.analysis_run_id)
        if row is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {result.analysis_run_id}")
        row.result_payload = result.model_dump(mode="json")
        row.updated_at = datetime.now(UTC)
        self._session.commit()
        return result

    def get_result(self, analysis_run_id: str) -> NarrativeAnalysisResultV1 | None:
        """Return a typed aggregate result without provider raw output."""

        row = self._session.get(NarrativeAnalysisRunModel, analysis_run_id)
        if row is None or row.result_payload is None:
            return None
        return NarrativeAnalysisResultV1.model_validate(row.result_payload)

    def claim_gate2_handoff(self, analysis_run_id: str) -> NarrativeAnalysisRunV1 | None:
        """Atomically claim a resumable Gate 2 handoff without touching analysis outputs."""

        row = self._session.get(NarrativeAnalysisRunModel, analysis_run_id)
        if row is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {analysis_run_id}")
        current = NarrativeAnalysisRunV1.model_validate(row.payload)
        if (
            current.review_gate2_result is not None
            and current.review_gate2_route is not None
        ):
            return None
        handoff = current.gate2_handoff
        if handoff is not None and handoff.status in {
            NarrativeGate2HandoffStatus.RUNNING,
            NarrativeGate2HandoffStatus.COMPLETED,
        }:
            return None
        attempts = handoff.attempt_count if handoff is not None else 0
        max_attempts = handoff.max_attempts if handoff is not None else 2
        if attempts >= max_attempts:
            return None
        now = datetime.now(UTC)
        claimed = current.model_copy(
            update={
                "schema_version": "1.5",
                "gate2_handoff": NarrativeGate2HandoffV1(
                    status=NarrativeGate2HandoffStatus.RUNNING,
                    attempt_count=attempts + 1,
                    max_attempts=max_attempts,
                    started_at=now,
                ),
                "updated_at": now,
            }
        )
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(NarrativeAnalysisRunModel)
                .where(
                    NarrativeAnalysisRunModel.analysis_run_id == analysis_run_id,
                    NarrativeAnalysisRunModel.updated_at == row.updated_at,
                )
                .values(
                    status=str(claimed.status),
                    payload=claimed.model_dump(mode="json"),
                    updated_at=now,
                )
            ),
        )
        self._session.commit()
        return claimed if result.rowcount else None

    def fail_gate2_handoff(
        self, *, analysis_run_id: str, failure_category: str
    ) -> NarrativeAnalysisRunV1:
        """Persist a source-free handoff failure while retaining aggregate and prior artifacts."""

        run = self.get_run(analysis_run_id)
        if run is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {analysis_run_id}")
        handoff = run.gate2_handoff or NarrativeGate2HandoffV1()
        return self.save_run(
            run.model_copy(
                update={
                    "schema_version": "1.5",
                    "gate2_handoff": handoff.model_copy(
                        update={
                            "status": NarrativeGate2HandoffStatus.FAILED,
                            "failure_category": failure_category,
                            "safe_issue_codes": ["GATE2_HANDOFF_FAILED"],
                            "completed_at": datetime.now(UTC),
                        }
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    def save_review_gate2_artifacts(
        self,
        *,
        analysis_run_id: str,
        result: ReviewGate2ResultV1,
        route: NarrativeAnalysisReviewRouteV1,
    ) -> NarrativeAnalysisRunV1:
        """Persist one typed Gate 2 result/route pair without replacing a prior audit."""

        run = self.get_run(analysis_run_id)
        if run is None:
            raise ValueError(f"NarrativeAnalysisRun not found: {analysis_run_id}")
        if run.review_gate2_result is not None and run.review_gate2_route is not None:
            return run
        handoff = run.gate2_handoff or NarrativeGate2HandoffV1()
        saved = run.model_copy(
            update={
                "schema_version": "1.5",
                "review_gate2_result": result,
                "review_gate2_route": route,
                "gate2_handoff": handoff.model_copy(
                    update={
                        "status": NarrativeGate2HandoffStatus.COMPLETED,
                        "safe_issue_codes": [],
                        "failure_category": None,
                        "completed_at": datetime.now(UTC),
                    }
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        return self.save_run(saved)

    def _create_window(self, window: NarrativeAnalysisWindowV1) -> None:
        existing = self._session.get(NarrativeAnalysisWindowModel, window.analysis_window_id)
        payload = window.model_dump(mode="json")
        if existing is not None:
            if existing.payload != payload:
                raise ValueError(
                    f"NarrativeAnalysisWindow conflict for id: {window.analysis_window_id}"
                )
            return

        # The recovery worker derives child IDs deterministically, but a resumed
        # worker can reach the same logical scope with a different legacy ID.
        # The database identity is (run, mode, window_index), so the first
        # durable row wins and a retry becomes a no-op instead of a raw
        # IntegrityError from the unique constraint.
        existing_scope = self._session.scalar(
            select(NarrativeAnalysisWindowModel).where(
                NarrativeAnalysisWindowModel.analysis_run_id == window.analysis_run_id,
                NarrativeAnalysisWindowModel.mode == window.mode,
                NarrativeAnalysisWindowModel.window_index == window.window_index,
            )
        )
        if existing_scope is not None:
            return

        now = datetime.now(UTC)
        try:
            # Flush inside a savepoint so a concurrent retry can be recovered
            # without poisoning the surrounding SQLAlchemy session.
            with self._session.begin_nested():
                self._session.add(
                    NarrativeAnalysisWindowModel(
                        analysis_window_id=window.analysis_window_id,
                        analysis_run_id=window.analysis_run_id,
                        mode=window.mode,
                        window_index=window.window_index,
                        status=str(window.status),
                        agent_run_id=window.agent_run_id,
                        payload=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._session.flush()
        except IntegrityError:
            # Another session may have won the unique scope between the read
            # above and the flush. Re-read after the savepoint rollback.
            existing_scope = self._session.scalar(
                select(NarrativeAnalysisWindowModel).where(
                    NarrativeAnalysisWindowModel.analysis_run_id == window.analysis_run_id,
                    NarrativeAnalysisWindowModel.mode == window.mode,
                    NarrativeAnalysisWindowModel.window_index == window.window_index,
                )
            )
            if existing_scope is None:
                raise
