"""Durable insert-only persistence for unified human production decisions."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import HumanReviewRunModel
from comic_agent.schemas.human_review import HumanReviewRunV1


class RepositoryConflictError(ValueError):
    """An immutable review identity already carries a different decision."""


# Backward-compatible name retained for existing callers during the repository swap.
HumanReviewConflictError = RepositoryConflictError


class HumanReviewRepository:
    """Persist exactly one human decision per dossier across process restarts."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_review_id(self, review_id: str) -> HumanReviewRunV1 | None:
        row = self._session.get(HumanReviewRunModel, review_id)
        return HumanReviewRunV1.model_validate(row.payload) if row is not None else None

    def get_by_dossier_id(self, dossier_id: str) -> HumanReviewRunV1 | None:
        row = self._session.scalar(
            select(HumanReviewRunModel).where(HumanReviewRunModel.dossier_id == dossier_id)
        )
        return HumanReviewRunV1.model_validate(row.payload) if row is not None else None

    def insert(self, run: HumanReviewRunV1) -> HumanReviewRunV1:
        """Insert once; return the existing matching decision after a race."""

        existing = self.get_by_dossier_id(run.dossier_id)
        if existing is not None:
            return self._matching_or_raise(existing, run)
        try:
            self._session.add(
                HumanReviewRunModel(
                    review_id=run.review_id,
                    project_id=run.project_id,
                    dossier_id=run.dossier_id,
                    dossier_hash=run.dossier_hash,
                    decision=str(run.decision),
                    payload=run.model_dump(mode="json"),
                    created_at=run.created_at,
                )
            )
            self._session.commit()
            return run
        except IntegrityError:
            self._session.rollback()
            winner = self.get_by_dossier_id(run.dossier_id)
            if winner is None:
                raise
            return self._matching_or_raise(winner, run)

    @staticmethod
    def _matching_or_raise(
        existing: HumanReviewRunV1, incoming: HumanReviewRunV1
    ) -> HumanReviewRunV1:
        if existing.decision != incoming.decision:
            raise RepositoryConflictError("a different human decision already exists for dossier")
        if (
            existing.project_id != incoming.project_id
            or existing.dossier_hash != incoming.dossier_hash
            or existing.lineage != incoming.lineage
            or existing.reviewer_id != incoming.reviewer_id
            or existing.reviewer_note != incoming.reviewer_note
        ):
            raise RepositoryConflictError("human review dossier identity is immutable")
        return existing
