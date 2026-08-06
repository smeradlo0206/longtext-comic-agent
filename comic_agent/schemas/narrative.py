"""Narrative extraction proposal schemas."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer, StrictBaseModel


class TemporalRelation(StrEnum):
    """Supported temporal relation labels."""

    BEFORE = "BEFORE"
    AFTER = "AFTER"
    DURING = "DURING"
    CONTAINS = "CONTAINS"
    OVERLAPS = "OVERLAPS"
    SIMULTANEOUS = "SIMULTANEOUS"
    UNKNOWN = "UNKNOWN"


class ActorResolutionStatus(StrEnum):
    """How EventProposalV1 resolves event participants or actors."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNRESOLVED = "UNRESOLVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSPECIFIED = "UNSPECIFIED"


class ClaimType(StrEnum):
    """Supported claim proposal kinds."""

    ASSERTION = "ASSERTION"
    FACTUAL_ASSERTION = "FACTUAL_ASSERTION"
    BELIEF = "BELIEF"
    DENIAL = "DENIAL"
    ACCUSATION = "ACCUSATION"
    HYPOTHESIS = "HYPOTHESIS"
    MEMORY = "MEMORY"
    EVALUATION = "EVALUATION"
    INTERPRETATION = "INTERPRETATION"
    PREDICTION = "PREDICTION"
    COMMITMENT = "COMMITMENT"


class ClaimTemporalScope(StrEnum):
    """Temporal scope of the claim proposition."""

    PAST = "PAST"
    PRESENT = "PRESENT"
    FUTURE = "FUTURE"
    ATEMPORAL = "ATEMPORAL"


class VerificationStatus(StrEnum):
    """Proposal-layer verification status for claims."""

    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNRESOLVED = "UNRESOLVED"


class ClaimSourceType(StrEnum):
    """Source family for a claim proposal."""

    CHARACTER = "CHARACTER"
    MESSAGE = "MESSAGE"
    NARRATOR = "NARRATOR"
    SYSTEM_LABEL = "SYSTEM_LABEL"
    AGENT = "AGENT"
    UNKNOWN = "UNKNOWN"


LEGACY_CLAIM_TYPE_VALUES = {
    "ASSERTION",
    "DENIAL",
    "ACCUSATION",
    "HYPOTHESIS",
    "MEMORY",
    "INTERPRETATION",
    "PREDICTION",
}


def _looks_like_legacy_claim_payload(value: Any) -> bool:
    """Detect old claim JSON that omitted schema_version before Claim v1.1."""

    if not isinstance(value, dict) or "schema_version" in value:
        return False
    claim_type = value.get("claim_type")
    if isinstance(claim_type, ClaimType):
        claim_type = claim_type.value
    return value.get("temporal_scope") is None and claim_type in LEGACY_CLAIM_TYPE_VALUES


class EpistemicStatus(StrEnum):
    """Character knowledge or belief state labels."""

    UNAWARE = "UNAWARE"
    HEARD = "HEARD"
    SUSPECTS = "SUSPECTS"
    BELIEVES = "BELIEVES"
    DISBELIEVES = "DISBELIEVES"
    KNOWS = "KNOWS"


class EntityProposalV1(StrictBaseModel):
    """Candidate entity discovered from source text."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    entity_type: str = Field(description="Entity type, e.g. CHARACTER, LOCATION, PROP.")
    canonical_name: str = Field(description="Proposed canonical name.")
    aliases: list[str] = Field(default_factory=list, description="Known aliases.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")


class EntityProposalBatchV1(StrictBaseModel):
    """Candidate story entities discovered from one bounded source context."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    batch_id: str = Field(description="Batch proposal id.")
    entities: list[EntityProposalV1] = Field(
        min_length=1,
        description="Candidate entity proposals in source order where possible.",
    )

    @model_validator(mode="after")
    def validate_unique_entity_ids(self) -> "EntityProposalBatchV1":
        """Keep batch outputs addressable by unique proposal id."""

        proposal_ids = [entity.proposal_id for entity in self.entities]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("entities must have unique proposal_id values")
        return self


class EventProposalV1(StrictBaseModel):
    """Candidate story event discovered from source text."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    event_type: str = Field(description="Event type label.")
    summary: str = Field(min_length=1, description="Faithful event summary.")
    participant_ids: list[str] = Field(default_factory=list, description="Participant entity ids.")
    actor_resolution_status: ActorResolutionStatus = Field(
        default=ActorResolutionStatus.UNSPECIFIED,
        description="How participant_ids should be interpreted for actor resolution.",
    )
    unresolved_actor_ref_id: str | None = Field(
        default=None,
        description="Optional future UnresolvedReference id for an unresolved actor mention.",
    )
    location_id: str | None = Field(default=None, description="Location entity id if known.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="At least one source evidence reference is required.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")

    @model_validator(mode="after")
    def validate_actor_resolution(self) -> "EventProposalV1":
        """Keep actor resolution explicit without inventing character ids."""

        status = self.actor_resolution_status
        if status == ActorResolutionStatus.KNOWN:
            if not self.participant_ids:
                raise ValueError("KNOWN actor resolution requires participant_ids")
            if self.unresolved_actor_ref_id is not None:
                raise ValueError("KNOWN actor resolution cannot include unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.UNKNOWN:
            if self.participant_ids:
                raise ValueError("UNKNOWN actor resolution requires empty participant_ids")
            if self.unresolved_actor_ref_id is not None:
                raise ValueError("UNKNOWN actor resolution cannot include unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.UNRESOLVED:
            if self.participant_ids:
                raise ValueError("UNRESOLVED actor resolution requires empty participant_ids")
            if self.unresolved_actor_ref_id is None:
                raise ValueError("UNRESOLVED actor resolution requires unresolved_actor_ref_id")
        elif status == ActorResolutionStatus.NOT_APPLICABLE:
            if self.participant_ids:
                raise ValueError("NOT_APPLICABLE actor resolution requires empty participant_ids")
            if self.unresolved_actor_ref_id is not None:
                raise ValueError(
                    "NOT_APPLICABLE actor resolution cannot include unresolved_actor_ref_id"
                )
        elif self.unresolved_actor_ref_id is not None:
            raise ValueError("UNSPECIFIED actor resolution cannot include unresolved_actor_ref_id")
        return self


class EventProposalBatchV1(StrictBaseModel):
    """Candidate story events discovered from one bounded source context."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    batch_id: str = Field(description="Batch proposal id.")
    events: list[EventProposalV1] = Field(
        min_length=1,
        description="Candidate event proposals in source order where possible.",
    )

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> "EventProposalBatchV1":
        """Keep batch outputs addressable by unique proposal id."""

        proposal_ids = [event.proposal_id for event in self.events]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("events must have unique proposal_id values")
        return self


class ClaimProposalV1(StrictBaseModel):
    """Candidate claim, statement, evaluation, denial, memory, or interpretation."""

    schema_version: Literal["1.0", "1.1", "1.2"] = Field(
        default="1.2",
        description="Schema version.",
    )
    proposal_id: str = Field(description="Proposal id.")
    claim_type: ClaimType = Field(description="Claim type.")
    claim_text: str = Field(description="Exact or faithful claim text.")
    temporal_scope: ClaimTemporalScope | None = Field(
        default=None,
        description="Temporal scope of the claim proposition; required for v1.1 and newer.",
    )
    source_type: ClaimSourceType = Field(description="Claim source family.")
    source_id: str | None = Field(default=None, description="Optional source object id.")
    target_event_id: str | None = Field(default=None, description="Optional target event id.")
    verification_status: VerificationStatus = Field(
        description="Proposal-layer verification status."
    )
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")

    @model_validator(mode="before")
    @classmethod
    def default_legacy_payload_version(cls, value: Any) -> Any:
        """Read old claim payloads that omitted schema_version as v1.0."""

        if _looks_like_legacy_claim_payload(value):
            return {**value, "schema_version": "1.0"}
        return value

    @field_validator("claim_text")
    @classmethod
    def claim_text_not_blank(cls, value: str) -> str:
        """Reject empty claim text."""

        if value.strip() == "":
            raise ValueError("claim_text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ClaimProposalV1":
        """Validate versioned claim semantics and source identity."""

        if self.schema_version in {"1.1", "1.2"}:
            if self.claim_type == ClaimType.ASSERTION:
                raise ValueError("ASSERTION is only supported for schema_version=1.0")
            if self.temporal_scope is None:
                raise ValueError("schema_version=1.1 and newer require temporal_scope")
        if self.schema_version != "1.2" and self.claim_type == ClaimType.EVALUATION:
            raise ValueError("EVALUATION is only supported for schema_version=1.2")
        if self.source_type == ClaimSourceType.UNKNOWN and self.source_id is not None:
            raise ValueError("UNKNOWN claim source cannot include source_id")
        return self


class ClaimProposalBatchV1(StrictBaseModel):
    """Candidate story claims discovered from one bounded source context."""

    schema_version: Literal["1.0", "1.1", "1.2"] = Field(
        default="1.2",
        description="Schema version.",
    )
    batch_id: str = Field(description="Batch proposal id.")
    claims: list[ClaimProposalV1] = Field(
        min_length=1,
        description="Candidate claim proposals in source order where possible.",
    )

    @model_validator(mode="before")
    @classmethod
    def default_legacy_batch_version(cls, value: Any) -> Any:
        """Read old claim batch payloads that omitted schema_version as v1.0."""

        if not isinstance(value, dict) or "schema_version" in value:
            return value
        claims = value.get("claims")
        if not isinstance(claims, list) or not claims:
            return value
        claim_versions: list[str | None] = []
        for claim in claims:
            if isinstance(claim, ClaimProposalV1):
                claim_versions.append(claim.schema_version)
            elif isinstance(claim, dict):
                claim_versions.append(
                    "1.0"
                    if _looks_like_legacy_claim_payload(claim)
                    else claim.get("schema_version")
                )
            else:
                claim_versions.append(None)
        if set(claim_versions) == {"1.0"}:
            return {**value, "schema_version": "1.0"}
        return value

    @model_validator(mode="after")
    def validate_unique_claim_ids(self) -> "ClaimProposalBatchV1":
        """Keep batch outputs addressable and version-consistent."""

        proposal_ids = [claim.proposal_id for claim in self.claims]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("claims must have unique proposal_id values")
        claim_versions = {claim.schema_version for claim in self.claims}
        if self.schema_version in {"1.1", "1.2"} and claim_versions != {
            self.schema_version
        }:
            raise ValueError(
                f"schema_version={self.schema_version} batch requires all claims to be "
                f"v{self.schema_version}"
            )
        if self.schema_version == "1.0" and claim_versions != {"1.0"}:
            raise ValueError("schema_version=1.0 batch requires all claims to be v1.0")
        return self


class KnowledgeStateProposalV1(StrictBaseModel):
    """Candidate character knowledge or belief state."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    character_id: str = Field(description="Character whose knowledge state is proposed.")
    knowledge_target_id: str = Field(description="Claim, event, fact, or target object id.")
    epistemic_status: EpistemicStatus = Field(description="Knowledge or belief status.")
    source_claim_id: str | None = Field(default=None, description="Optional source claim id.")
    valid_from_event_id: str | None = Field(
        default=None,
        description="Optional event id from which the state becomes valid.",
    )
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")


class TemporalRelationProposalV1(StrictBaseModel):
    """Candidate temporal relation between two events."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    source_event_id: str = Field(description="Source event id.")
    target_event_id: str = Field(description="Target event id.")
    relation: TemporalRelation = Field(description="Temporal relation label.")
    offset_value: int | None = Field(default=None, description="Optional time offset value.")
    offset_unit: str | None = Field(default=None, description="Optional time offset unit.")
    evidence_refs: list[EvidenceRefV1] = Field(
        default_factory=list,
        description="Evidence required when relation is known.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")

    @model_validator(mode="after")
    def validate_relation(self) -> "TemporalRelationProposalV1":
        """Reject self loops and unsupported UNKNOWN offsets."""

        if self.source_event_id == self.target_event_id:
            raise ValueError("source_event_id and target_event_id cannot be the same")
        if self.relation == TemporalRelation.UNKNOWN:
            if self.offset_value is not None or self.offset_unit is not None:
                raise ValueError("UNKNOWN relation cannot include offset")
        elif not self.evidence_refs:
            raise ValueError("known temporal relations require at least one EvidenceRef")
        return self


class StateChangeProposalV1(StrictBaseModel):
    """Candidate state mutation caused by an event."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    event_id: str = Field(description="Event causing this change.")
    target_entity_id: str = Field(description="Entity whose state changes.")
    attribute_path: str = Field(description="Dotted state path, e.g. appearance.hair.")
    old_value: Any | None = Field(default=None, description="Previous value if known.")
    new_value: Any | None = Field(default=None, description="New value if known.")
    persistent: bool = Field(description="Whether this state persists after the event.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
