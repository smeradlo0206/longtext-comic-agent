"""Repository ports used by StoryBible application services."""

from contextlib import AbstractContextManager
from typing import Protocol

from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    CommitPlanV1,
    StoryBibleReviewRunV1,
    StoryBibleUpdateV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)


class StoryBibleCanonicalRepositoryPort(Protocol):
    """Canonical persistence operations required by commit and freeze services."""

    def get_matching_committed_plan(self, plan: CommitPlanV1) -> CommitPlanV1 | None: ...

    def preflight_commit_plan(self, plan: CommitPlanV1) -> None: ...

    def commit_unit_of_work(self) -> AbstractContextManager[None]: ...

    def save_candidate_plan(self, plan: CommitPlanV1) -> CommitPlanV1: ...

    def list_profiles(self, project_id: str) -> list[StoryEntityProfileV1]: ...

    def list_states(self, project_id: str) -> list[StoryEntityStateV1]: ...

    def list_relationships(self, project_id: str) -> list[StoryRelationshipV1]: ...

    def list_world_rules(self, project_id: str) -> list[WorldRuleV1]: ...

    def apply_canonical_update(self, update: StoryBibleUpdateV1, plan_id: str) -> object: ...

    def save_committed_plan(self, plan: CommitPlanV1) -> CommitPlanV1: ...


class StoryBibleReviewRepositoryPort(Protocol):
    """Review persistence operations required by the freeze service."""

    def get_review(self, review_id: str) -> StoryBibleReviewRunV1 | None: ...

    def freeze(
        self, review_id: str, bundle: ApprovedStoryBibleBundleV1
    ) -> StoryBibleReviewRunV1: ...
