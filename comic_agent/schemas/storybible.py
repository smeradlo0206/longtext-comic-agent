"""Versioned, evidence-backed contracts for StoryBible curation."""

from datetime import UTC, datetime
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
from comic_agent.schemas.source import SourceChunkV1


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
    """Reviewed list of StoryBible updates eligible for CommitService processing."""

    schema_version: Literal["1.0"] = "1.0"
    commit_plan_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId
    content_hash: StoryBibleId
    updates: list[StoryBibleUpdateV1] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("commit_plan_id", "project_id", "source_proposal_id", "content_hash")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


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


class StoryBibleProductionRunStatus(StrEnum):
    """Execution-only lifecycle for one production curator checkpoint."""

    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class StoryBibleProductionFailureStage(StrEnum):
    """Sanitized execution boundary at which production curation stopped."""

    INPUT_ADAPTATION = "INPUT_ADAPTATION"
    CONTEXT_BUDGET = "CONTEXT_BUDGET"
    PROVIDER = "PROVIDER"
    SCHEMA = "SCHEMA"
    NORMALIZATION = "NORMALIZATION"
    AGENT_RUN_PERSISTENCE = "AGENT_RUN_PERSISTENCE"
    RUN_CHECKPOINT_PERSISTENCE = "RUN_CHECKPOINT_PERSISTENCE"


class StoryBibleProductionInputV1(StrictBaseModel):
    """Server-built references to approved inputs for production curation."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId
    approved_timeline_bundle_id: StoryBibleId
    canonical_storybible_snapshot_hash: StoryBibleId

    @field_validator(
        "project_id",
        "gate2_approved_bundle_id",
        "approved_timeline_bundle_id",
        "canonical_storybible_snapshot_hash",
    )
    @classmethod
    def production_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleCanonicalSnapshotV1(StrictBaseModel):
    """Deterministically ordered canonical StoryBible state used by production."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def snapshot_project_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_snapshot_scope_and_order(self) -> "StoryBibleCanonicalSnapshotV1":
        collections = (
            (self.profiles, "profile_id"),
            (self.states, "state_id"),
            (self.relationships, "relationship_id"),
            (self.world_rules, "rule_id"),
        )
        for resources, id_field in collections:
            if any(resource.project_id != self.project_id for resource in resources):
                raise ValueError("canonical snapshot resources must belong to its project")
            ids = [getattr(resource, id_field) for resource in resources]
            if ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError("canonical snapshot resources must be unique and id-sorted")
        return self


class StoryBibleTrustedEventOrderV1(StrictBaseModel):
    """Approved strict predecessors and an order only when they form a total order."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: StoryBibleId
    strict_predecessor_event_ids: list[StoryBibleId] = Field(default_factory=list)
    resolved_order: int | None = Field(default=None, ge=0)

    @field_validator("event_id")
    @classmethod
    def event_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_predecessors(self) -> "StoryBibleTrustedEventOrderV1":
        if self.event_id in self.strict_predecessor_event_ids:
            raise ValueError("event cannot precede itself")
        if self.strict_predecessor_event_ids != sorted(self.strict_predecessor_event_ids):
            raise ValueError("strict predecessor ids must be sorted")
        if len(self.strict_predecessor_event_ids) != len(
            set(self.strict_predecessor_event_ids)
        ):
            raise ValueError("strict predecessor ids must be unique")
        return self


class StoryBibleProductionContextV1(StrictBaseModel):
    """Server-built trusted context derived only from approved persisted artifacts."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId
    narrative_analysis_run_id: StoryBibleId
    approved_timeline_bundle_id: StoryBibleId
    timeline_run_id: StoryBibleId
    approved_entities: list[EntityProposalV1] = Field(default_factory=list)
    approved_events: list[EventProposalV1] = Field(default_factory=list)
    approved_state_changes: list[StateChangeProposalV1] = Field(default_factory=list)
    approved_temporal_relations: list[TemporalRelationProposalV1] = Field(
        default_factory=list
    )
    trusted_event_ids: list[StoryBibleId] = Field(default_factory=list)
    trusted_event_order: list[StoryBibleTrustedEventOrderV1] = Field(default_factory=list)
    trusted_evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list)
    source_chunks: list[SourceChunkV1] = Field(default_factory=list)
    canonical_snapshot: StoryBibleCanonicalSnapshotV1
    canonical_storybible_snapshot_hash: StoryBibleId

    @field_validator(
        "project_id",
        "gate2_approved_bundle_id",
        "narrative_analysis_run_id",
        "approved_timeline_bundle_id",
        "timeline_run_id",
        "canonical_storybible_snapshot_hash",
    )
    @classmethod
    def context_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_trusted_context(self) -> "StoryBibleProductionContextV1":
        if self.canonical_snapshot.project_id != self.project_id:
            raise ValueError("canonical snapshot must belong to the context project")
        if self.trusted_event_ids != sorted(self.trusted_event_ids) or len(
            self.trusted_event_ids
        ) != len(set(self.trusted_event_ids)):
            raise ValueError("trusted event ids must be unique and sorted")
        approved_event_ids = {event.proposal_id for event in self.approved_events}
        if set(self.trusted_event_ids) != approved_event_ids:
            raise ValueError("trusted event ids must exactly match approved events")
        order_ids = [item.event_id for item in self.trusted_event_order]
        if order_ids != self.trusted_event_ids:
            raise ValueError("trusted event order must cover trusted events in id order")
        if any(
            not set(item.strict_predecessor_event_ids).issubset(approved_event_ids)
            for item in self.trusted_event_order
        ):
            raise ValueError("event order references an untrusted event")
        if self.source_chunk_ids != sorted(self.source_chunk_ids) or len(
            self.source_chunk_ids
        ) != len(set(self.source_chunk_ids)):
            raise ValueError("source chunk ids must be unique and sorted")
        if {ref.chunk_id for ref in self.trusted_evidence_refs} != set(
            self.source_chunk_ids
        ):
            raise ValueError("source chunk ids must exactly match trusted evidence")
        chunk_ids = [chunk.chunk_id for chunk in self.source_chunks]
        if chunk_ids != self.source_chunk_ids:
            raise ValueError("source chunks must cover trusted chunk ids in id order")
        if any(chunk.project_id != self.project_id for chunk in self.source_chunks):
            raise ValueError("source chunks must belong to the context project")
        return self


class StoryBibleProductionRunV1(StrictBaseModel):
    """Durable, resumable execution checkpoint for production StoryBible curation."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    run_id: StoryBibleId
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId
    approved_timeline_bundle_id: StoryBibleId
    canonical_storybible_snapshot_hash: StoryBibleId
    input_hash: StoryBibleId
    model_identity: StoryBibleName
    status: StoryBibleProductionRunStatus
    curator_proposal: StoryBibleCuratorProposalV1 | None = None
    agent_run_id: StoryBibleId | None = None
    provider_request_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    failure_stage: StoryBibleProductionFailureStage | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "run_id",
        "project_id",
        "gate2_approved_bundle_id",
        "approved_timeline_bundle_id",
        "canonical_storybible_snapshot_hash",
        "input_hash",
        "model_identity",
    )
    @classmethod
    def run_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("error_message")
    @classmethod
    def error_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            return _reject_blank(value)
        return value

    @model_validator(mode="after")
    def validate_execution_checkpoint(self) -> "StoryBibleProductionRunV1":
        if self.status == StoryBibleProductionRunStatus.SUCCEEDED:
            if self.curator_proposal is None or self.agent_run_id is None:
                raise ValueError("SUCCEEDED run requires curator_proposal and agent_run_id")
            if self.provider_request_count < 1:
                raise ValueError("SUCCEEDED run requires a provider request")
            if self.curator_proposal.project_id != self.project_id:
                raise ValueError("curator proposal must belong to the run project")
        elif self.curator_proposal is not None:
            raise ValueError("only SUCCEEDED runs may contain curator output")
        elif self.agent_run_id is not None and self.status != StoryBibleProductionRunStatus.FAILED:
            raise ValueError("only terminal runs may contain AgentRun provenance")
        if self.status == StoryBibleProductionRunStatus.FAILED:
            if self.error_message is None:
                raise ValueError("FAILED run requires error_message")
        elif self.error_message is not None or self.failure_stage is not None:
            raise ValueError("only FAILED runs may contain failure details")
        if self.status == StoryBibleProductionRunStatus.RESERVED and self.provider_request_count:
            raise ValueError("RESERVED run cannot contain provider requests")
        return self
