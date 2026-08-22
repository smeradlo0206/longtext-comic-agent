"""Persistence boundary for deterministic StoryBible review and freeze records."""

from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import (
    StoryBibleProductionRunModel,
    StoryBibleReviewRunModel,
)
from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.ports.storybible import StoryBibleReviewRepositoryPort
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryBibleReviewContextV1,
    StoryBibleReviewDecision,
    StoryBibleReviewResultV1,
    StoryBibleReviewRunStatus,
    StoryBibleReviewRunV1,
)


class StoryBibleReviewRepository(StoryBibleReviewRepositoryPort):
    """Store one review per production run and freeze its bundle at most once."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_review(
        self,
        context: StoryBibleReviewContextV1,
        result: StoryBibleReviewResultV1,
    ) -> StoryBibleReviewRunV1:
        """Persist a deterministic result without changing its production run."""

        source_run = self._validate_source_run(context, result)
        existing = self.get_by_source_run(result.storybible_run_id)
        if existing is not None:
            return self._matching_review_or_raise(existing, result)
        now = result.reviewed_at
        review_run = StoryBibleReviewRunV1(
            review_id=result.review_id,
            project_id=result.project_id,
            source_storybible_run_id=result.storybible_run_id,
            source_approved_timeline_bundle_id=source_run.approved_timeline_bundle_id,
            canonical_snapshot=context.canonical_snapshot,
            canonical_snapshot_hash=source_run.canonical_storybible_snapshot_hash,
            proposal_hash=result.proposal_hash,
            review_result=result,
            created_at=now,
            updated_at=now,
        )
        try:
            self._session.add(self._row(review_run))
            self._session.commit()
            return review_run
        except IntegrityError:
            self._session.rollback()
            winner = self.get_by_source_run(result.storybible_run_id)
            if winner is None:
                raise
            return self._matching_review_or_raise(winner, result)

    def get_review(self, review_id: str) -> StoryBibleReviewRunV1 | None:
        row = self._session.get(StoryBibleReviewRunModel, review_id)
        return StoryBibleReviewRunV1.model_validate(row.payload) if row else None

    def get_by_source_run(self, source_run_id: str) -> StoryBibleReviewRunV1 | None:
        row = self._session.scalar(
            select(StoryBibleReviewRunModel).where(
                StoryBibleReviewRunModel.source_storybible_run_id == source_run_id
            )
        )
        return StoryBibleReviewRunV1.model_validate(row.payload) if row else None

    def freeze(
        self,
        review_id: str,
        bundle: ApprovedStoryBibleBundleV1,
    ) -> StoryBibleReviewRunV1:
        """Atomically attach the only permitted immutable bundle to an approved review."""

        review_run = self._require_review(review_id)
        if review_run.status == StoryBibleReviewRunStatus.FROZEN:
            if review_run.approved_bundle == bundle:
                return review_run
            raise ValueError("frozen StoryBible bundle is immutable")
        if review_run.review_result.decision != StoryBibleReviewDecision.APPROVE:
            raise ValueError("only an APPROVE StoryBible review may be frozen")
        frozen_at = bundle.review_metadata.frozen_at
        updated = StoryBibleReviewRunV1.model_validate(
            review_run.model_dump()
            | {
                "status": StoryBibleReviewRunStatus.FROZEN,
                "approved_bundle": bundle.model_dump(mode="json"),
                "updated_at": frozen_at,
                "frozen_at": frozen_at,
            }
        )
        result = self._session.execute(
            update(StoryBibleReviewRunModel)
            .where(
                StoryBibleReviewRunModel.review_id == review_run.review_id,
                StoryBibleReviewRunModel.status == str(StoryBibleReviewRunStatus.REVIEWED),
            )
            .values(
                status=str(updated.status),
                bundle_id=bundle.bundle_id,
                snapshot_hash=bundle.snapshot_hash,
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
                frozen_at=updated.frozen_at,
            )
        )
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            winner = self._require_review(review_id)
            if winner.approved_bundle == bundle:
                return winner
            raise ValueError("frozen StoryBible bundle identity already exists") from None
        if cast(CursorResult[object], result).rowcount == 1:
            return updated
        winner = self._require_review(review_id)
        if winner.approved_bundle == bundle:
            return winner
        raise ValueError("StoryBible review changed concurrently")

    def _validate_source_run(
        self,
        context: StoryBibleReviewContextV1,
        result: StoryBibleReviewResultV1,
    ) -> StoryBibleProductionRunV1:
        row = self._session.get(StoryBibleProductionRunModel, result.storybible_run_id)
        if row is None:
            raise ValueError("StoryBible production run not found")
        run = StoryBibleProductionRunV1.model_validate(row.payload)
        if run.project_id != result.project_id:
            raise ValueError("StoryBible production run belongs to another project")
        if run.status != StoryBibleProductionRunStatus.SUCCEEDED:
            raise ValueError("only a SUCCEEDED StoryBible production run may be reviewed")
        if (
            context.review_id != result.review_id
            or context.project_id != result.project_id
            or context.source_storybible_run_id != result.storybible_run_id
            or context.proposal_hash != result.proposal_hash
        ):
            raise ValueError("StoryBible review context does not match its result")
        if (
            context.source_approved_timeline_bundle_id
            != run.approved_timeline_bundle_id
            or context.canonical_snapshot_hash
            != run.canonical_storybible_snapshot_hash
        ):
            raise ValueError("StoryBible review context has invalid production lineage")
        if run.curator_proposal is None:
            raise ValueError("StoryBible production run has no curator proposal")
        if storybible_proposal_hash(run.curator_proposal) != result.proposal_hash:
            raise ValueError("StoryBible review proposal hash does not match production")
        return run

    def _require_review(self, review_id: str) -> StoryBibleReviewRunV1:
        review = self.get_review(review_id)
        if review is None:
            raise ValueError(f"StoryBible review not found: {review_id}")
        return review

    @staticmethod
    def _matching_review_or_raise(
        existing: StoryBibleReviewRunV1,
        result: StoryBibleReviewResultV1,
    ) -> StoryBibleReviewRunV1:
        stored = existing.review_result.model_dump(exclude={"reviewed_at"})
        incoming = result.model_dump(exclude={"reviewed_at"})
        if stored == incoming:
            return existing
        raise ValueError("StoryBible production run already has a different review")

    @staticmethod
    def _row(review_run: StoryBibleReviewRunV1) -> StoryBibleReviewRunModel:
        return StoryBibleReviewRunModel(
            review_id=review_run.review_id,
            project_id=review_run.project_id,
            source_storybible_run_id=review_run.source_storybible_run_id,
            proposal_hash=review_run.proposal_hash,
            status=str(review_run.status),
            bundle_id=None,
            snapshot_hash=None,
            payload=review_run.model_dump(mode="json"),
            created_at=review_run.created_at,
            updated_at=review_run.updated_at,
            frozen_at=None,
        )
