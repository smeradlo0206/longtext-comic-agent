"""Persistence for idempotent long-text comic production runs."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from comic_agent.database.models import ComicProductionRunModel
from comic_agent.schemas.comic_production import ComicProductionRunV1


class ComicProductionRepository:
    """Store non-canonical production plans, queue state, and artifact locations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get(self, run: ComicProductionRunV1) -> ComicProductionRunV1:
        existing = self._session.scalar(
            select(ComicProductionRunModel).where(
                ComicProductionRunModel.project_id == run.project_id,
                ComicProductionRunModel.document_id == run.document_id,
                ComicProductionRunModel.request_hash == run.request_hash,
            )
        )
        if existing is not None:
            return ComicProductionRunV1.model_validate(existing.payload)
        self._session.add(
            ComicProductionRunModel(
                run_id=run.run_id,
                project_id=run.project_id,
                document_id=run.document_id,
                request_hash=run.request_hash,
                status=str(run.status),
                payload=run.model_dump(mode="json"),
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
        )
        self._session.commit()
        return run

    def get(self, run_id: str) -> ComicProductionRunV1 | None:
        row = self._session.get(ComicProductionRunModel, run_id)
        return ComicProductionRunV1.model_validate(row.payload) if row is not None else None

    def save(self, run: ComicProductionRunV1) -> ComicProductionRunV1:
        row = self._session.get(ComicProductionRunModel, run.run_id)
        if row is None:
            raise ValueError(f"comic production run not found: {run.run_id}")
        updated = run.model_copy(update={"updated_at": datetime.now(UTC)})
        row.status = str(updated.status)
        row.payload = updated.model_dump(mode="json")
        row.updated_at = updated.updated_at
        self._session.commit()
        return updated

    def list_for_project(self, project_id: str) -> list[ComicProductionRunV1]:
        rows = self._session.scalars(
            select(ComicProductionRunModel)
            .where(ComicProductionRunModel.project_id == project_id)
            .order_by(ComicProductionRunModel.created_at, ComicProductionRunModel.run_id)
        ).all()
        return [ComicProductionRunV1.model_validate(row.payload) for row in rows]
