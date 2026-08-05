"""Versioned, evidence-backed contracts for StoryBible curation."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

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


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class StoryEntityProfileV1(StrictBaseModel):
    """Canonical identity record for a person, organization, or location."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    project_id: str
    entity_kind: StoryEntityKind
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
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
    state_id: str
    project_id: str
    profile_id: str
    state: dict[str, Any] = Field(default_factory=dict)
    triggering_event_id: str | None = None
    valid_from_event_id: str | None = None
    valid_until_event_id: str | None = None
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
    relationship_id: str
    project_id: str
    source_profile_id: str
    target_profile_id: str
    relationship_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from_event_id: str | None = None
    valid_until_event_id: str | None = None
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
    rule_id: str
    project_id: str
    name: str
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
    update_id: str
    project_id: str
    profile: StoryEntityProfileV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class StateUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a time-bound entity state."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: str
    project_id: str
    state: StoryEntityStateV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class RelationshipUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a typed relationship."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: str
    project_id: str
    relationship: StoryRelationshipV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class WorldRuleUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a world rule."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: str
    project_id: str
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
    conflict_id: str
    project_id: str
    category: str
    summary: str
    affected_update_ids: list[str] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    blocking: bool = True

    @field_validator("conflict_id", "project_id", "category", "summary")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class CommitPlanV1(StrictBaseModel):
    """Reviewed list of StoryBible updates eligible for CommitService processing."""

    schema_version: Literal["1.0"] = "1.0"
    commit_plan_id: str
    project_id: str
    source_proposal_id: str
    content_hash: str
    updates: list[StoryBibleUpdateV1] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("commit_plan_id", "project_id", "source_proposal_id", "content_hash")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleContextV1(StrictBaseModel):
    """Bounded context supplied to the proposal-only StoryBible curator."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    entity_proposals: list[EntityProposalV1] = Field(default_factory=list)
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)
    temporal_relation_proposals: list[TemporalRelationProposalV1] = Field(default_factory=list)
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("project_id")
    @classmethod
    def project_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleCuratorProposalV1(StrictBaseModel):
    """Proposal-only output returned by the StoryBible Curator."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str
    project_id: str
    status: RecordStatus = RecordStatus.CANDIDATE
    commit_plan: CommitPlanV1
    conflicts: list[ConflictV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("proposal_id", "project_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)
