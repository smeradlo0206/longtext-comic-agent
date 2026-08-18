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
from comic_agent.schemas.review import (
    NarrativeAnalysisReviewRouteV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
)
from comic_agent.schemas.timeline import (
    NarrativeTimelineReviewRouteV1,
    ReviewGate3Decision,
)


class StoryEntityKind(StrEnum):
    """Entity kinds that are eligible for canonical StoryBible profiles."""

    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"


class StoryBibleCanonicalKind(StrEnum):
    """Long-lived identifier namespace owned by StoryBible."""

    EVENT = "EVENT"
    PROFILE = "PROFILE"
    STATE = "STATE"
    RELATIONSHIP = "RELATIONSHIP"
    WORLD_RULE = "WORLD_RULE"


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


class StoryBibleIdentityBindingV1(StrictBaseModel):
    """Mapping from a reviewed upstream proposal id to a durable StoryBible id."""

    schema_version: Literal["1.0"] = "1.0"
    source_schema: StoryBibleId
    source_proposal_id: StoryBibleId
    canonical_kind: StoryBibleCanonicalKind
    canonical_id: StoryBibleId
    project_id: StoryBibleId

    @field_validator(
        "source_schema", "source_proposal_id", "canonical_id", "project_id"
    )
    @classmethod
    def binding_values_are_nonblank(cls, value: str) -> str:
        return _reject_blank(value)


class ProfileUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of an entity profile, emitted by the curator."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId | None = None
    profile: StoryEntityProfileV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class StateUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a time-bound entity state."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId | None = None
    state: StoryEntityStateV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class RelationshipUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a typed relationship."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId | None = None
    relationship: StoryRelationshipV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class WorldRuleUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a world rule."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId | None = None
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
    """Bounded context admitted only from the existing Gate 2 and Gate 3 routes."""

    schema_version: Literal["1.1"] = "1.1"
    project_id: StoryBibleId
    gate2_route: NarrativeAnalysisReviewRouteV1
    gate3_route: NarrativeTimelineReviewRouteV1
    entity_proposals: list[EntityProposalV1] = Field(default_factory=list)
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)
    temporal_relation_proposals: list[TemporalRelationProposalV1] = Field(default_factory=list)
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)
    identity_bindings: list[StoryBibleIdentityBindingV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list, max_length=3)

    @field_validator("project_id")
    @classmethod
    def project_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def require_approved_gate_routes(self) -> "StoryBibleContextV1":
        """Reject raw or partial inputs before StoryBible curation can start."""

        gate2 = self.gate2_route
        if (
            gate2.decision != ReviewGate2RoutingDecision.APPROVED
            or gate2.review_status != ReviewGate2RunStatus.COMPLETED
            or gate2.approved_proposal_bundle is None
        ):
            raise ValueError("StoryBible context requires an APPROVED Gate 2 route with a bundle")
        gate3 = self.gate3_route
        if (
            gate3.route != ReviewGate3Decision.APPROVED
            or gate3.approved_timeline_bundle is None
        ):
            raise ValueError("StoryBible context requires an APPROVED Gate 3 route with a bundle")

        gate2_bundle = gate2.approved_proposal_bundle
        gate3_bundle = gate3.approved_timeline_bundle
        if gate2_bundle.project_id != self.project_id or gate3_bundle.project_id != self.project_id:
            raise ValueError("Gate 2 and Gate 3 bundles must belong to the context project")
        if gate3_bundle.source_approved_proposal_bundle_id != gate2_bundle.bundle_id:
            raise ValueError("Gate 3 bundle must be derived from the approved Gate 2 bundle")
        if gate3_bundle.source_gate2_review_id != gate2_bundle.review_run_id:
            raise ValueError("Gate 3 bundle must retain the Gate 2 review id")
        if gate3_bundle.source_gate2_route_id != gate2.analysis_run_id:
            raise ValueError("Gate 3 bundle must retain the Gate 2 route id")

        approved_proposals = [item.source.proposal for item in gate2_bundle.approved_proposals]
        expected_entities = [
            proposal for proposal in approved_proposals if isinstance(proposal, EntityProposalV1)
        ][:3]
        expected_events = [
            proposal for proposal in approved_proposals if isinstance(proposal, EventProposalV1)
        ][:3]
        expected_states = [
            proposal
            for proposal in approved_proposals
            if isinstance(proposal, StateChangeProposalV1)
        ][:3]
        expected_temporal = gate3_bundle.temporal_relations[:3]
        if self.entity_proposals != expected_entities:
            raise ValueError("StoryBible entity proposals must come from the Gate 2 bundle")
        if self.event_proposals != expected_events:
            raise ValueError("StoryBible event proposals must come from the Gate 2 bundle")
        if self.state_change_proposals != expected_states:
            raise ValueError("StoryBible state proposals must come from the Gate 2 bundle")
        if self.temporal_relation_proposals != expected_temporal:
            raise ValueError("StoryBible temporal proposals must come from the Gate 3 bundle")

        all_proposal_ids = [
            proposal.proposal_id
            for proposals in (
                self.entity_proposals,
                self.event_proposals,
                self.state_change_proposals,
                self.temporal_relation_proposals,
            )
            for proposal in proposals
        ]
        if len(all_proposal_ids) != len(set(all_proposal_ids)):
            raise ValueError("StoryBible context proposal ids must be globally unique")

        binding_keys = [
            (binding.source_schema, binding.source_proposal_id)
            for binding in self.identity_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("identity_bindings must be unique per source schema and proposal id")
        expected_binding_keys = {
            ("EntityProposalV1", proposal.proposal_id)
            for proposal in self.entity_proposals
        }
        expected_binding_keys.update(
            ("EventProposalV1", proposal.proposal_id) for proposal in self.event_proposals
        )
        expected_binding_keys.update(
            ("StateChangeProposalV1", proposal.proposal_id)
            for proposal in self.state_change_proposals
        )
        expected_binding_keys.update(
            ("TemporalRelationProposalV1", proposal.proposal_id)
            for proposal in self.temporal_relation_proposals
        )
        if set(binding_keys) != expected_binding_keys:
            raise ValueError(
                "identity_bindings must cover exactly the admitted Gate 2/Gate 3 proposals"
            )
        for binding in self.identity_bindings:
            if binding.project_id != self.project_id:
                raise ValueError("identity binding project must match StoryBible context")
        return self


class StoryBibleCuratorProposalV1(StrictBaseModel):
    """Proposal-only output returned by the StoryBible Curator."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: StoryBibleId
    project_id: StoryBibleId
    status: RecordStatus = RecordStatus.CANDIDATE
    commit_plan: CommitPlanV1
    identity_bindings: list[StoryBibleIdentityBindingV1] = Field(default_factory=list)
    conflicts: list[ConflictV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("proposal_id", "project_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)
