"""Project-scoped persistence for StoryBible resources and candidate plans."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import (
    CandidateCommitPlanModel,
    StoryEntityProfileModel,
    StoryEntityStateModel,
    StoryRelationshipModel,
    WorldRuleModel,
)
from comic_agent.ports.storybible import StoryBibleCanonicalRepositoryPort
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)

type CanonicalResource = (
    StoryEntityProfileV1 | StoryEntityStateV1 | StoryRelationshipV1 | WorldRuleV1
)
type CanonicalUpdate = (
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1
)
type RelatedResource = StoryEntityStateV1 | StoryRelationshipV1
UPDATE_TYPES = (
    ProfileUpdateProposalV1,
    StateUpdateProposalV1,
    RelationshipUpdateProposalV1,
    WorldRuleUpdateProposalV1,
)


class StoryBibleRepository(StoryBibleCanonicalRepositoryPort):
    """Data access layer that keeps all StoryBible queries project-scoped."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._atomic_write_depth = 0

    @contextmanager
    def commit_unit_of_work(self) -> Iterator[None]:
        """Commit all enclosed StoryBible writes together or roll them all back."""

        if self._atomic_write_depth:
            raise RuntimeError("nested StoryBible commit units of work are not supported")
        self._atomic_write_depth = 1
        try:
            yield
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._atomic_write_depth = 0

    def _finish_write(self) -> None:
        """Flush inside a commit unit of work; otherwise preserve standalone commits."""

        if self._atomic_write_depth:
            self._session.flush()
        else:
            self._session.commit()

    def save_candidate_plan(self, plan: CommitPlanV1) -> CommitPlanV1:
        """Persist a candidate once per project and deterministic content hash."""

        existing_hash = self._session.scalar(
            select(CandidateCommitPlanModel).where(
                CandidateCommitPlanModel.project_id == plan.project_id,
                CandidateCommitPlanModel.content_hash == plan.content_hash,
            )
        )
        if existing_hash is not None:
            return self._require_matching_plan(existing_hash, plan)

        existing_id = self._session.get(CandidateCommitPlanModel, plan.commit_plan_id)
        if existing_id is not None:
            if (
                existing_id.project_id == plan.project_id
                and existing_id.content_hash == plan.content_hash
            ):
                return self._require_matching_plan(existing_id, plan)
            raise ValueError("commit_plan_id already belongs to a different plan")

        self._session.add(
            CandidateCommitPlanModel(
                commit_plan_id=plan.commit_plan_id,
                project_id=plan.project_id,
                source_proposal_id=plan.source_proposal_id,
                content_hash=plan.content_hash,
                status="CANDIDATE",
                payload=plan.model_dump(mode="json"),
            )
        )
        try:
            self._finish_write()
        except IntegrityError as error:
            if self._atomic_write_depth:
                raise
            self._session.rollback()
            existing_hash = self._session.scalar(
                select(CandidateCommitPlanModel).where(
                    CandidateCommitPlanModel.project_id == plan.project_id,
                    CandidateCommitPlanModel.content_hash == plan.content_hash,
                )
            )
            if existing_hash is not None:
                return self._require_matching_plan(existing_hash, plan)
            existing_id = self._session.get(CandidateCommitPlanModel, plan.commit_plan_id)
            if existing_id is not None:
                if (
                    existing_id.project_id == plan.project_id
                    and existing_id.content_hash == plan.content_hash
                ):
                    return self._require_matching_plan(existing_id, plan)
                raise ValueError(
                    "commit_plan_id already belongs to a different plan"
                ) from error
            raise
        return plan

    def _require_matching_plan(
        self,
        existing_row: CandidateCommitPlanModel,
        incoming_plan: CommitPlanV1,
    ) -> CommitPlanV1:
        """Reuse only an identical plan for a project-scoped content hash."""

        existing_plan = self._plan_from_row(existing_row)
        if existing_plan.model_dump(mode="json") != incoming_plan.model_dump(mode="json"):
            raise ValueError("content_hash already belongs to a different commit plan")
        return existing_plan

    def save_committed_plan(self, plan: CommitPlanV1) -> CommitPlanV1:
        """Persist a plan if needed and mark it as committed idempotently."""

        stored = self.save_candidate_plan(plan)
        row = self._session.get(CandidateCommitPlanModel, stored.commit_plan_id)
        if row is None:  # pragma: no cover - guarded by save_candidate_plan
            raise RuntimeError("candidate plan was not persisted")
        if row.status != "COMMITTED":
            row.status = "COMMITTED"
            self._finish_write()
        return self._plan_from_row(row)

    def get_plan(self, project_id: str, plan_id: str) -> CommitPlanV1 | None:
        """Return a plan only when it belongs to the requested project."""

        row = self._session.scalar(
            select(CandidateCommitPlanModel).where(
                CandidateCommitPlanModel.project_id == project_id,
                CandidateCommitPlanModel.commit_plan_id == plan_id,
            )
        )
        return None if row is None else self._plan_from_row(row)

    def get_matching_committed_plan(self, plan: CommitPlanV1) -> CommitPlanV1 | None:
        """Return an exact committed retry while rejecting id or payload substitution."""

        row = self._session.get(CandidateCommitPlanModel, plan.commit_plan_id)
        if row is None or row.status != "COMMITTED":
            return None
        if row.project_id != plan.project_id or row.content_hash != plan.content_hash:
            raise ValueError("commit_plan_id already belongs to a different plan")
        return self._require_matching_plan(row, plan)

    def get_plan_by_content_hash(
        self, project_id: str, content_hash: str
    ) -> CommitPlanV1 | None:
        """Return the existing project plan for a deterministic content hash."""

        row = self._session.scalar(
            select(CandidateCommitPlanModel).where(
                CandidateCommitPlanModel.project_id == project_id,
                CandidateCommitPlanModel.content_hash == content_hash,
            )
        )
        return None if row is None else self._plan_from_row(row)

    def preflight_commit_plan(self, plan: CommitPlanV1) -> None:
        """Reject global resource and profile-reference conflicts before writes."""

        existing_plan = self._session.get(CandidateCommitPlanModel, plan.commit_plan_id)
        if existing_plan is not None and (
            existing_plan.project_id != plan.project_id
            or existing_plan.content_hash != plan.content_hash
        ):
            raise ValueError("commit_plan_id already belongs to a different plan")

        planned_profile_ids = {
            update.profile.profile_id
            for update in plan.updates
            if isinstance(update, ProfileUpdateProposalV1)
        }
        referenced_profile_ids: set[str] = set()

        for proposed_update in plan.updates:
            resource = self._unwrap_update(proposed_update)
            if isinstance(resource, StoryEntityProfileV1):
                stored_project_id = self._session.scalar(
                    select(StoryEntityProfileModel.project_id).where(
                        StoryEntityProfileModel.profile_id == resource.profile_id
                    )
                )
            elif isinstance(resource, StoryEntityStateV1):
                stored_project_id = self._session.scalar(
                    select(StoryEntityStateModel.project_id).where(
                        StoryEntityStateModel.state_id == resource.state_id
                    )
                )
            elif isinstance(resource, StoryRelationshipV1):
                stored_project_id = self._session.scalar(
                    select(StoryRelationshipModel.project_id).where(
                        StoryRelationshipModel.relationship_id
                        == resource.relationship_id
                    )
                )
            else:
                stored_project_id = self._session.scalar(
                    select(WorldRuleModel.project_id).where(
                        WorldRuleModel.rule_id == resource.rule_id
                    )
                )
            if stored_project_id is not None:
                self._guard_project(stored_project_id, resource.project_id)
            if isinstance(resource, StoryEntityStateV1):
                referenced_profile_ids.add(resource.profile_id)
            elif isinstance(resource, StoryRelationshipV1):
                referenced_profile_ids.update(
                    (resource.source_profile_id, resource.target_profile_id)
                )

        for profile_id in sorted(referenced_profile_ids - planned_profile_ids):
            stored_project_id = self._session.scalar(
                select(StoryEntityProfileModel.project_id).where(
                    StoryEntityProfileModel.profile_id == profile_id
                )
            )
            if stored_project_id is None:
                raise ValueError(f"canonical update references nonexistent profile: {profile_id}")
            self._guard_project(stored_project_id, plan.project_id)

    def get_profile(self, project_id: str, profile_id: str) -> StoryEntityProfileV1 | None:
        """Return one profile only when it belongs to the requested project."""

        row = self._session.scalar(
            select(StoryEntityProfileModel).where(
                StoryEntityProfileModel.project_id == project_id,
                StoryEntityProfileModel.profile_id == profile_id,
            )
        )
        return None if row is None else self._profile_from_row(row)

    def list_profiles(self, project_id: str) -> list[StoryEntityProfileV1]:
        """Return canonical profiles owned by one project in stable id order."""

        rows = self._session.scalars(
            select(StoryEntityProfileModel)
            .where(StoryEntityProfileModel.project_id == project_id)
            .order_by(StoryEntityProfileModel.profile_id)
        ).all()
        return [self._profile_from_row(row) for row in rows]

    def list_states(self, project_id: str) -> list[StoryEntityStateV1]:
        """Return all canonical states for deterministic commit validation."""

        rows = self._session.scalars(
            select(StoryEntityStateModel)
            .where(StoryEntityStateModel.project_id == project_id)
            .order_by(StoryEntityStateModel.state_id)
        ).all()
        return [StoryEntityStateV1.model_validate(row.payload) for row in rows]

    def list_relationships(self, project_id: str) -> list[StoryRelationshipV1]:
        """Return canonical relationships owned by one project in stable id order."""

        rows = self._session.scalars(
            select(StoryRelationshipModel)
            .where(StoryRelationshipModel.project_id == project_id)
            .order_by(StoryRelationshipModel.relationship_id)
        ).all()
        return [StoryRelationshipV1.model_validate(row.payload) for row in rows]

    def find_profiles(self, project_id: str, query: str) -> list[StoryEntityProfileV1]:
        """Find exact case-insensitive canonical-name or alias matches in one project."""

        rows = self._session.scalars(
            select(StoryEntityProfileModel)
            .where(StoryEntityProfileModel.project_id == project_id)
            .order_by(StoryEntityProfileModel.profile_id)
        ).all()
        normalized_query = query.casefold()
        return [
            profile
            for profile in map(self._profile_from_row, rows)
            if normalized_query
            in {
                profile.canonical_name.casefold(),
                *(alias.casefold() for alias in profile.aliases),
            }
        ]

    def list_states_at_event(
        self,
        project_id: str,
        event_order: int,
        profile_id: str | None = None,
    ) -> list[StoryEntityStateV1]:
        """Return states active at an inclusive story event order."""

        statement = select(StoryEntityStateModel).where(
            StoryEntityStateModel.project_id == project_id,
            or_(
                StoryEntityStateModel.valid_from_order.is_(None),
                StoryEntityStateModel.valid_from_order <= event_order,
            ),
            or_(
                StoryEntityStateModel.valid_until_order.is_(None),
                StoryEntityStateModel.valid_until_order >= event_order,
            ),
        )
        if profile_id is not None:
            statement = statement.where(StoryEntityStateModel.profile_id == profile_id)
        rows = self._session.scalars(statement.order_by(StoryEntityStateModel.state_id)).all()
        return [StoryEntityStateV1.model_validate(row.payload) for row in rows]

    def list_related_resources(
        self, project_id: str, profile_id: str
    ) -> list[RelatedResource]:
        """Return canonical states and relationships connected to one profile."""

        state_rows = self._session.scalars(
            select(StoryEntityStateModel)
            .where(
                StoryEntityStateModel.project_id == project_id,
                StoryEntityStateModel.profile_id == profile_id,
            )
            .order_by(StoryEntityStateModel.state_id)
        ).all()
        relationship_rows = self._session.scalars(
            select(StoryRelationshipModel)
            .where(
                StoryRelationshipModel.project_id == project_id,
                or_(
                    StoryRelationshipModel.source_profile_id == profile_id,
                    StoryRelationshipModel.target_profile_id == profile_id,
                ),
            )
            .order_by(StoryRelationshipModel.relationship_id)
        ).all()
        states = [StoryEntityStateV1.model_validate(row.payload) for row in state_rows]
        relationships = [
            StoryRelationshipV1.model_validate(row.payload) for row in relationship_rows
        ]
        return [*states, *relationships]

    def list_world_rules(self, project_id: str) -> list[WorldRuleV1]:
        """Return canonical world rules owned by one project."""

        rows = self._session.scalars(
            select(WorldRuleModel)
            .where(WorldRuleModel.project_id == project_id)
            .order_by(WorldRuleModel.rule_id)
        ).all()
        return [WorldRuleV1.model_validate(row.payload) for row in rows]

    def apply_canonical_update(
        self, update: CanonicalResource | CanonicalUpdate, plan_id: str
    ) -> CanonicalResource:
        """Insert or revision-gate one canonical update idempotently."""

        resource = self._unwrap_update(update)
        if resource.status != RecordStatus.CANONICAL:
            raise ValueError("canonical update resource status must be CANONICAL")
        if isinstance(update, UPDATE_TYPES) and update.project_id != resource.project_id:
            raise ValueError("update and canonical resource must belong to the same project")
        if isinstance(resource, StoryEntityProfileV1):
            return self._apply_profile(resource, plan_id)
        if isinstance(resource, StoryEntityStateV1):
            return self._apply_state(resource, plan_id)
        if isinstance(resource, StoryRelationshipV1):
            return self._apply_relationship(resource, plan_id)
        return self._apply_world_rule(resource, plan_id)

    @staticmethod
    def _unwrap_update(update: CanonicalResource | CanonicalUpdate) -> CanonicalResource:
        if isinstance(update, ProfileUpdateProposalV1):
            return update.profile
        if isinstance(update, StateUpdateProposalV1):
            return update.state
        if isinstance(update, RelationshipUpdateProposalV1):
            return update.relationship
        if isinstance(update, WorldRuleUpdateProposalV1):
            return update.world_rule
        return update

    def _apply_profile(
        self, profile: StoryEntityProfileV1, plan_id: str
    ) -> StoryEntityProfileV1:
        row = self._session.get(StoryEntityProfileModel, profile.profile_id)
        if row is None:
            row = StoryEntityProfileModel(
                profile_id=profile.profile_id,
                project_id=profile.project_id,
                entity_kind=str(profile.entity_kind),
                canonical_name=profile.canonical_name,
                revision=profile.revision,
                last_plan_id=plan_id,
                payload=profile.model_dump(mode="json"),
            )
            self._session.add(row)
            try:
                self._finish_write()
            except IntegrityError:
                if self._atomic_write_depth:
                    raise
                self._session.rollback()
                if self._session.get(StoryEntityProfileModel, profile.profile_id) is None:
                    raise
            else:
                return profile

        row = self._session.scalar(
            select(StoryEntityProfileModel)
            .where(StoryEntityProfileModel.profile_id == profile.profile_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("canonical profile insert failed without a stored winner")
        self._guard_project(row.project_id, profile.project_id)
        self._session.execute(
            update(StoryEntityProfileModel)
            .where(
                StoryEntityProfileModel.profile_id == profile.profile_id,
                StoryEntityProfileModel.project_id == profile.project_id,
                StoryEntityProfileModel.revision < profile.revision,
            )
            .values(
                entity_kind=str(profile.entity_kind),
                canonical_name=profile.canonical_name,
                revision=profile.revision,
                last_plan_id=plan_id,
                payload=profile.model_dump(mode="json"),
            )
            .execution_options(synchronize_session=False)
        )
        self._finish_write()
        row = self._session.scalar(
            select(StoryEntityProfileModel)
            .where(StoryEntityProfileModel.profile_id == profile.profile_id)
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - canonical rows are not deleted here
            raise RuntimeError("canonical profile disappeared after update")
        return self._profile_from_row(row)

    def _apply_state(self, state: StoryEntityStateV1, plan_id: str) -> StoryEntityStateV1:
        row = self._session.get(StoryEntityStateModel, state.state_id)
        if row is None:
            row = StoryEntityStateModel(
                state_id=state.state_id,
                project_id=state.project_id,
                profile_id=state.profile_id,
                valid_from_order=state.valid_from_order,
                valid_until_order=state.valid_until_order,
                revision=state.revision,
                last_plan_id=plan_id,
                payload=state.model_dump(mode="json"),
            )
            self._session.add(row)
            try:
                self._finish_write()
            except IntegrityError:
                if self._atomic_write_depth:
                    raise
                self._session.rollback()
                if self._session.get(StoryEntityStateModel, state.state_id) is None:
                    raise
            else:
                return state

        row = self._session.scalar(
            select(StoryEntityStateModel)
            .where(StoryEntityStateModel.state_id == state.state_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("canonical state insert failed without a stored winner")
        self._guard_project(row.project_id, state.project_id)
        self._session.execute(
            update(StoryEntityStateModel)
            .where(
                StoryEntityStateModel.state_id == state.state_id,
                StoryEntityStateModel.project_id == state.project_id,
                StoryEntityStateModel.revision < state.revision,
            )
            .values(
                profile_id=state.profile_id,
                valid_from_order=state.valid_from_order,
                valid_until_order=state.valid_until_order,
                revision=state.revision,
                last_plan_id=plan_id,
                payload=state.model_dump(mode="json"),
            )
            .execution_options(synchronize_session=False)
        )
        self._finish_write()
        row = self._session.scalar(
            select(StoryEntityStateModel)
            .where(StoryEntityStateModel.state_id == state.state_id)
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - canonical rows are not deleted here
            raise RuntimeError("canonical state disappeared after update")
        return StoryEntityStateV1.model_validate(row.payload)

    def _apply_relationship(
        self, relationship: StoryRelationshipV1, plan_id: str
    ) -> StoryRelationshipV1:
        row = self._session.get(StoryRelationshipModel, relationship.relationship_id)
        if row is None:
            row = StoryRelationshipModel(
                relationship_id=relationship.relationship_id,
                project_id=relationship.project_id,
                source_profile_id=relationship.source_profile_id,
                target_profile_id=relationship.target_profile_id,
                valid_from_order=relationship.valid_from_order,
                valid_until_order=relationship.valid_until_order,
                revision=relationship.revision,
                last_plan_id=plan_id,
                payload=relationship.model_dump(mode="json"),
            )
            self._session.add(row)
            try:
                self._finish_write()
            except IntegrityError:
                if self._atomic_write_depth:
                    raise
                self._session.rollback()
                if (
                    self._session.get(
                        StoryRelationshipModel, relationship.relationship_id
                    )
                    is None
                ):
                    raise
            else:
                return relationship

        row = self._session.scalar(
            select(StoryRelationshipModel)
            .where(StoryRelationshipModel.relationship_id == relationship.relationship_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("canonical relationship insert failed without a stored winner")
        self._guard_project(row.project_id, relationship.project_id)
        self._session.execute(
            update(StoryRelationshipModel)
            .where(
                StoryRelationshipModel.relationship_id == relationship.relationship_id,
                StoryRelationshipModel.project_id == relationship.project_id,
                StoryRelationshipModel.revision < relationship.revision,
            )
            .values(
                source_profile_id=relationship.source_profile_id,
                target_profile_id=relationship.target_profile_id,
                valid_from_order=relationship.valid_from_order,
                valid_until_order=relationship.valid_until_order,
                revision=relationship.revision,
                last_plan_id=plan_id,
                payload=relationship.model_dump(mode="json"),
            )
            .execution_options(synchronize_session=False)
        )
        self._finish_write()
        row = self._session.scalar(
            select(StoryRelationshipModel)
            .where(StoryRelationshipModel.relationship_id == relationship.relationship_id)
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - canonical rows are not deleted here
            raise RuntimeError("canonical relationship disappeared after update")
        return StoryRelationshipV1.model_validate(row.payload)

    def _apply_world_rule(self, rule: WorldRuleV1, plan_id: str) -> WorldRuleV1:
        row = self._session.get(WorldRuleModel, rule.rule_id)
        if row is None:
            row = WorldRuleModel(
                rule_id=rule.rule_id,
                project_id=rule.project_id,
                name=rule.name,
                revision=rule.revision,
                last_plan_id=plan_id,
                payload=rule.model_dump(mode="json"),
            )
            self._session.add(row)
            try:
                self._finish_write()
            except IntegrityError:
                if self._atomic_write_depth:
                    raise
                self._session.rollback()
                if self._session.get(WorldRuleModel, rule.rule_id) is None:
                    raise
            else:
                return rule

        row = self._session.scalar(
            select(WorldRuleModel)
            .where(WorldRuleModel.rule_id == rule.rule_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("canonical world rule insert failed without a stored winner")
        self._guard_project(row.project_id, rule.project_id)
        self._session.execute(
            update(WorldRuleModel)
            .where(
                WorldRuleModel.rule_id == rule.rule_id,
                WorldRuleModel.project_id == rule.project_id,
                WorldRuleModel.revision < rule.revision,
            )
            .values(
                name=rule.name,
                revision=rule.revision,
                last_plan_id=plan_id,
                payload=rule.model_dump(mode="json"),
            )
            .execution_options(synchronize_session=False)
        )
        self._finish_write()
        row = self._session.scalar(
            select(WorldRuleModel)
            .where(WorldRuleModel.rule_id == rule.rule_id)
            .execution_options(populate_existing=True)
        )
        if row is None:  # pragma: no cover - canonical rows are not deleted here
            raise RuntimeError("canonical world rule disappeared after update")
        return WorldRuleV1.model_validate(row.payload)

    @staticmethod
    def _guard_project(stored_project_id: str, incoming_project_id: str) -> None:
        if stored_project_id != incoming_project_id:
            raise ValueError("canonical resource id already belongs to another project")

    @staticmethod
    def _profile_from_row(row: StoryEntityProfileModel) -> StoryEntityProfileV1:
        return StoryEntityProfileV1.model_validate(row.payload)

    @staticmethod
    def _plan_from_row(row: CandidateCommitPlanModel) -> CommitPlanV1:
        return CommitPlanV1.model_validate(row.payload)
