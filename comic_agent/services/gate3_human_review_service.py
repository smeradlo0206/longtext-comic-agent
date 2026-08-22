"""Explicit human resolution for persisted Gate 3 review holds."""

from datetime import UTC, datetime

from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.timeline import (
    ApprovedTimelineBundleV1,
    Gate3HumanReviewInputV1,
    Gate3HumanReviewResolution,
    Gate3HumanReviewV1,
    ReviewGate3Decision,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
)
from comic_agent.services.review_gate3_service import ReviewGate3Service


class Gate3HumanReviewService:
    """Resolve the existing Gate 3 run without rerunning Timeline or automated review."""

    def __init__(self, repository: TimelineGate3Repository) -> None:
        self._repository = repository

    def review_gate3_run(
        self,
        review: Gate3HumanReviewInputV1,
        *,
        project_id: str | None = None,
    ) -> TimelineGate3RunV1:
        run = self._repository.get_run(review.gate3_run_id)
        if run is None:
            raise Gate3HumanReviewNotFoundError(
                f"Timeline Gate 3 run not found: {review.gate3_run_id}"
            )
        if project_id is not None and run.project_id != project_id:
            raise Gate3HumanReviewNotFoundError(
                f"Timeline Gate 3 run not found: {review.gate3_run_id}"
            )
        if run.status != TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW:
            repeated = self._resolved_repeat_or_raise(run, review)
            return self._finalize_approval_if_needed(repeated)
        if run.gate3_result is None or run.gate3_result.decision != str(
            ReviewGate3Decision.NEEDS_HUMAN_REVIEW
        ):
            raise Gate3HumanReviewConflictError(
                "Gate 3 run has no automated human-review hold"
            )

        now = datetime.now(UTC)
        final_decision = (
            ReviewGate3Decision.APPROVED
            if review.resolution == Gate3HumanReviewResolution.APPROVE
            else ReviewGate3Decision.REJECTED
        )
        human_review = Gate3HumanReviewV1(
            **review.model_dump(),
            reviewed_at=now,
            final_decision=final_decision,
        )
        bundle = (
            self._build_approved_bundle(run)
            if final_decision == ReviewGate3Decision.APPROVED
            else None
        )
        resolved = TimelineGate3RunV1.model_validate(
            run.model_dump()
            | {
                "status": TimelineGate3RunStatus(final_decision),
                "gate3_result": run.gate3_result.model_copy(
                    update={
                        "human_review": human_review,
                        "effective_decision": final_decision,
                    }
                ),
                "approved_timeline_bundle": bundle,
                "updated_at": now,
            }
        )
        if self._repository.apply_human_review(resolved):
            return resolved
        winner = self._repository.get_run(review.gate3_run_id)
        if winner is None:
            raise Gate3HumanReviewNotFoundError(
                f"Timeline Gate 3 run not found: {review.gate3_run_id}"
            )
        repeated = self._resolved_repeat_or_raise(winner, review)
        return self._finalize_approval_if_needed(repeated)

    def _finalize_approval_if_needed(self, run: TimelineGate3RunV1) -> TimelineGate3RunV1:
        if (
            run.status != TimelineGate3RunStatus.APPROVED
            or run.approved_timeline_bundle is not None
        ):
            return run
        now = datetime.now(UTC)
        finalized = TimelineGate3RunV1.model_validate(
            run.model_dump()
            | {
                "approved_timeline_bundle": self._build_approved_bundle(run),
                "updated_at": now,
            }
        )
        if self._repository.finalize_human_approval(finalized):
            return finalized
        winner = self._repository.get_run(run.timeline_run_id)
        if winner is None or winner.approved_timeline_bundle is None:
            raise RuntimeError("Human-approved Gate 3 bundle finalization failed")
        return winner

    @staticmethod
    def _build_approved_bundle(run: TimelineGate3RunV1) -> ApprovedTimelineBundleV1:
        if (
            run.timeline_input is None
            or run.timeline_proposal is None
            or run.gate3_result is None
            or run.gate3_route is None
        ):
            raise RuntimeError("Gate 3 run lacks persisted Timeline approval inputs")
        bundle = ReviewGate3Service.build_approved_bundle(
            decision=ReviewGate3Decision.APPROVED,
            route_id=run.gate3_route.route_id,
            review_id=run.gate3_result.review_id,
            project_id=run.project_id,
            source_bundle_id=run.source_approved_proposal_bundle_id,
            source_gate2_review_id=run.source_gate2_review_id,
            source_gate2_route_id=run.source_gate2_route_id,
            timeline_run_id=run.timeline_run_id,
            relations=run.timeline_proposal.temporal_relations,
            event_ids=[item.proposal_id for item in run.timeline_input.event_proposals],
            evidence=run.timeline_proposal.evidence_refs,
        )
        if bundle is None:
            raise RuntimeError("Approved Timeline bundle construction failed")
        return bundle

    @staticmethod
    def _resolved_repeat_or_raise(
        run: TimelineGate3RunV1,
        review: Gate3HumanReviewInputV1,
    ) -> TimelineGate3RunV1:
        stored = run.gate3_result.human_review if run.gate3_result is not None else None
        if stored is not None and (
            stored.gate3_run_id == review.gate3_run_id
            and stored.resolution == review.resolution
            and stored.reviewer_id == review.reviewer_id
            and stored.note == review.note
        ):
            return run
        raise Gate3HumanReviewConflictError("Timeline Gate 3 run is not awaiting human review")


class Gate3HumanReviewNotFoundError(ValueError):
    """The requested project-scoped Gate 3 run does not exist."""


class Gate3HumanReviewConflictError(ValueError):
    """The requested review conflicts with the persisted Gate 3 state."""
