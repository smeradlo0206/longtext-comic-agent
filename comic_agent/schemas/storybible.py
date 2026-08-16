"""Versioned, evidence-backed contracts for StoryBible curation."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus, StrictBaseModel
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)


class StoryEntityKind(StrEnum):
    """Entity kinds that are eligible for canonical StoryBible profiles."""

    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"


StoryBibleId = Annotated[str, StringConstraints(max_length=128)]
StoryBibleName = Annotated[str, StringConstraints(max_length=255)]


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class StoryEntityProfileV1(StrictBaseModel):
    """Canonical identity record for a person, organization, or location."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: StoryBibleId
    project_id: StoryBibleId
    entity_kind: StoryEntityKind
    canonical_name: StoryBibleName
    aliases: list[StoryBibleName] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("profile_id", "project_id", "canonical_name")
    @classmethod
    def identifiers_and_name_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("aliases")
    @classmethod
    def aliases_are_not_blank(cls, value: list[str]) -> list[str]:
        return [_reject_blank(alias) for alias in value]


class StoryEntityStateV1(StrictBaseModel):
    """Evidence-backed state that applies to a profile over a story-time interval."""

    schema_version: Literal["1.0"] = "1.0"
    state_id: StoryBibleId
    project_id: StoryBibleId
    profile_id: StoryBibleId
    state: dict[str, Any] = Field(default_factory=dict)
    triggering_event_id: StoryBibleId | None = None
    valid_from_event_id: StoryBibleId | None = None
    valid_until_event_id: StoryBibleId | None = None
    valid_from_order: int | None = Field(default=None, ge=0)
    valid_until_order: int | None = Field(default=None, ge=0)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("state_id", "project_id", "profile_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def temporal_interval_is_valid(self) -> "StoryEntityStateV1":
        if (
            self.valid_from_order is not None
            and self.valid_until_order is not None
            and self.valid_until_order < self.valid_from_order
        ):
            raise ValueError("valid_until_order must not precede valid_from_order")
        return self


class StoryRelationshipV1(StrictBaseModel):
    """Typed, time-bound relationship between two StoryBible profiles."""

    schema_version: Literal["1.0"] = "1.0"
    relationship_id: StoryBibleId
    project_id: StoryBibleId
    source_profile_id: StoryBibleId
    target_profile_id: StoryBibleId
    relationship_type: StoryBibleName
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from_event_id: StoryBibleId | None = None
    valid_until_event_id: StoryBibleId | None = None
    valid_from_order: int | None = Field(default=None, ge=0)
    valid_until_order: int | None = Field(default=None, ge=0)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator(
        "relationship_id",
        "project_id",
        "source_profile_id",
        "target_profile_id",
        "relationship_type",
    )
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def relationship_interval_is_valid(self) -> "StoryRelationshipV1":
        if self.source_profile_id == self.target_profile_id:
            raise ValueError("relationship endpoints cannot be the same")
        if (
            self.valid_from_order is not None
            and self.valid_until_order is not None
            and self.valid_until_order < self.valid_from_order
        ):
            raise ValueError("valid_until_order must not precede valid_from_order")
        return self


class WorldRuleV1(StrictBaseModel):
    """Source-supported rule governing the story world."""

    schema_version: Literal["1.0"] = "1.0"
    rule_id: StoryBibleId
    project_id: StoryBibleId
    name: StoryBibleName
    statement: str
    scope: str | None = None
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("rule_id", "project_id", "name", "statement")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class ProfileUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of an entity profile, emitted by the curator."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    profile: StoryEntityProfileV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class StateUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a time-bound entity state."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    state: StoryEntityStateV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class RelationshipUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a typed relationship."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    relationship: StoryRelationshipV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class WorldRuleUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a world rule."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    world_rule: WorldRuleV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


StoryBibleUpdateV1 = Annotated[
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1,
    Field(discriminator=None),
]


class ConflictV1(StrictBaseModel):
    """Reviewable evidence, identity, or temporal conflict in a curation candidate."""

    schema_version: Literal["1.0"] = "1.0"
    conflict_id: StoryBibleId
    project_id: StoryBibleId
    category: str
    summary: str
    affected_update_ids: list[StoryBibleId] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    blocking: bool = True

    @field_validator("conflict_id", "project_id", "category", "summary")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class CommitPlanV1(StrictBaseModel):
    """Reviewed list of StoryBible updates eligible for CommitService processing.

    ``content_hash`` is optional on input: the curator and the curation API always
    replace it with a deterministic SHA-256 hash of the plan content (excluding the
    hash field itself) before the candidate plan is persisted, so provider output can
    neither forge nor collide the idempotency key.
    """

    schema_version: Literal["1.0"] = "1.0"
    commit_plan_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId
    content_hash: StoryBibleId | None = None
    updates: list[StoryBibleUpdateV1] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("commit_plan_id", "project_id", "source_proposal_id")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("content_hash")
    @classmethod
    def content_hash_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            return _reject_blank(value)
        return value


class StoryBibleContextV1(StrictBaseModel):
    """Bounded context supplied to the proposal-only StoryBible curator."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    entity_proposals: list[EntityProposalV1] = Field(default_factory=list)
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)
    temporal_relation_proposals: list[TemporalRelationProposalV1] = Field(default_factory=list)
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list, max_length=3)

    @field_validator("project_id")
    @classmethod
    def project_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleCuratorProposalV1(StrictBaseModel):
    """Proposal-only output returned by the StoryBible Curator."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: StoryBibleId
    project_id: StoryBibleId
    status: RecordStatus = RecordStatus.CANDIDATE
    commit_plan: CommitPlanV1
    conflicts: list[ConflictV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("proposal_id", "project_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)
