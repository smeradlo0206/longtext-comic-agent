"""Freeze an approved StoryBible review through the canonical commit boundary."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.ports.storybible import (
    StoryBibleCanonicalRepositoryPort,
    StoryBibleReviewRepositoryPort,
)
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    CommitPlanV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryBibleReviewDecision,
    StoryBibleReviewMetadataV1,
    StoryBibleReviewRunStatus,
    WorldRuleUpdateProposalV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.id_service import stable_id
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)


class StoryBibleFreezeService:
    """Commit an approved proposal once, then persist its immutable canonical bundle."""

    def __init__(
        self,
        *,
        review_repository: StoryBibleReviewRepositoryPort,
        storybible_repository: StoryBibleCanonicalRepositoryPort,
        commit_service: CommitService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reviews = review_repository
        self._storybible = storybible_repository
        self._commit = commit_service
        self._clock = clock or (lambda: datetime.now(UTC))

    def freeze(
        self,
        review_id: str,
        *,
        production_run: StoryBibleProductionRunV1,
        approved_timeline: ApprovedTimelineBundleV1,
    ) -> ApprovedStoryBibleBundleV1:
        review = self._reviews.get_review(review_id)
        if review is None:
            raise ValueError(f"StoryBible review not found: {review_id}")
        if review.status == StoryBibleReviewRunStatus.FROZEN:
            if review.approved_bundle is None:  # guarded by the schema
                raise RuntimeError("frozen StoryBible review has no approved bundle")
            return review.approved_bundle
        if review.review_result.decision != StoryBibleReviewDecision.APPROVE:
            raise ValueError("only an APPROVE StoryBible review may be frozen")
        if production_run.status != StoryBibleProductionRunStatus.SUCCEEDED:
            raise ValueError("StoryBible production run is not SUCCEEDED")
        if (
            production_run.run_id != review.source_storybible_run_id
            or production_run.project_id != review.project_id
        ):
            raise ValueError("StoryBible production lineage mismatch")
        if (
            approved_timeline.bundle_id != review.source_approved_timeline_bundle_id
            or approved_timeline.bundle_id
            != production_run.approved_timeline_bundle_id
            or approved_timeline.project_id != review.project_id
        ):
            raise ValueError("Approved Timeline lineage mismatch")
        proposal = production_run.curator_proposal
        if proposal is None:
            raise ValueError("StoryBible production run has no curator proposal")
        if storybible_proposal_hash(proposal) != review.proposal_hash:
            raise ValueError("StoryBible proposal hash mismatch")

        receipt = self._storybible.get_matching_committed_plan(proposal.commit_plan)
        if receipt is None:
            before = self._snapshot(review.project_id)
            before_hash = canonical_storybible_snapshot_hash(before)
            if (
                before_hash != review.canonical_snapshot_hash
                or before_hash != production_run.canonical_storybible_snapshot_hash
            ):
                raise ValueError("canonical StoryBible snapshot changed before freeze")

            # The freeze service never writes canonical rows directly.
            self._commit.commit_storybible_plan(proposal.commit_plan, self._storybible)
        snapshot = self._snapshot(review.project_id)
        snapshot_hash = canonical_storybible_snapshot_hash(snapshot)
        expected_hash = canonical_storybible_snapshot_hash(
            self._expected_snapshot(review.canonical_snapshot, proposal.commit_plan)
        )
        if snapshot_hash != expected_hash:
            raise ValueError("committed StoryBible snapshot does not match the reviewed plan")
        frozen_at = self._clock()
        evidence_refs = self._evidence_refs(snapshot)
        bundle = ApprovedStoryBibleBundleV1(
            bundle_id=stable_id("approved-storybible", review.review_id, snapshot_hash),
            project_id=review.project_id,
            source_storybible_run_id=review.source_storybible_run_id,
            snapshot_hash=snapshot_hash,
            entities=snapshot.profiles,
            relationships=snapshot.relationships,
            world_rules=snapshot.world_rules,
            state_changes=snapshot.states,
            evidence_refs=evidence_refs,
            review_metadata=StoryBibleReviewMetadataV1(
                review_id=review.review_id,
                decision=StoryBibleReviewDecision.APPROVE,
                proposal_hash=review.proposal_hash,
                source_approved_timeline_bundle_id=approved_timeline.bundle_id,
                reviewed_at=review.review_result.reviewed_at,
                frozen_at=frozen_at,
            ),
        )
        return self._reviews.freeze(review.review_id, bundle).approved_bundle or bundle

    def _snapshot(self, project_id: str) -> StoryBibleCanonicalSnapshotV1:
        return StoryBibleCanonicalSnapshotV1(
            project_id=project_id,
            profiles=self._storybible.list_profiles(project_id),
            states=self._storybible.list_states(project_id),
            relationships=self._storybible.list_relationships(project_id),
            world_rules=self._storybible.list_world_rules(project_id),
        )

    @staticmethod
    def _expected_snapshot(
        base: StoryBibleCanonicalSnapshotV1,
        plan: CommitPlanV1,
    ) -> StoryBibleCanonicalSnapshotV1:
        profiles = {item.profile_id: item for item in base.profiles}
        states = {item.state_id: item for item in base.states}
        relationships = {item.relationship_id: item for item in base.relationships}
        world_rules = {item.rule_id: item for item in base.world_rules}
        for update in plan.updates:
            if isinstance(update, ProfileUpdateProposalV1):
                current_profile = profiles.get(update.profile.profile_id)
                if (
                    current_profile is None
                    or current_profile.revision < update.profile.revision
                ):
                    profiles[update.profile.profile_id] = update.profile
            elif isinstance(update, StateUpdateProposalV1):
                current_state = states.get(update.state.state_id)
                if current_state is None or current_state.revision < update.state.revision:
                    states[update.state.state_id] = update.state
            elif isinstance(update, RelationshipUpdateProposalV1):
                current_relationship = relationships.get(update.relationship.relationship_id)
                if (
                    current_relationship is None
                    or current_relationship.revision < update.relationship.revision
                ):
                    relationships[update.relationship.relationship_id] = update.relationship
            elif isinstance(update, WorldRuleUpdateProposalV1):
                current_rule = world_rules.get(update.world_rule.rule_id)
                if current_rule is None or current_rule.revision < update.world_rule.revision:
                    world_rules[update.world_rule.rule_id] = update.world_rule
        return StoryBibleCanonicalSnapshotV1(
            project_id=base.project_id,
            profiles=sorted(profiles.values(), key=lambda item: item.profile_id),
            states=sorted(states.values(), key=lambda item: item.state_id),
            relationships=sorted(
                relationships.values(), key=lambda item: item.relationship_id
            ),
            world_rules=sorted(world_rules.values(), key=lambda item: item.rule_id),
        )

    @staticmethod
    def _evidence_refs(snapshot: StoryBibleCanonicalSnapshotV1) -> list[EvidenceRefV1]:
        values = [
            ref
            for resources in (
                snapshot.profiles,
                snapshot.states,
                snapshot.relationships,
                snapshot.world_rules,
            )
            for resource in resources
            for ref in resource.evidence_refs
        ]
        keyed = {
            json.dumps(
                ref.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ): ref
            for ref in values
        }
        return [keyed[key] for key in sorted(keyed)]
