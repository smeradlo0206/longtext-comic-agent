"""Persistence for resumable whole-document narrative analysis tasks."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from comic_agent.database.models import NarrativeAnalysisRunModel, NarrativeAnalysisWindowModel
from comic_agent.schemas.workflow import (
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowV1,
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

    def _create_window(self, window: NarrativeAnalysisWindowV1) -> None:
        existing = self._session.get(NarrativeAnalysisWindowModel, window.analysis_window_id)
        payload = window.model_dump(mode="json")
        if existing is None:
            now = datetime.now(UTC)
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
        elif existing.payload != payload:
            raise ValueError(
                f"NarrativeAnalysisWindow conflict for id: {window.analysis_window_id}"
            )
