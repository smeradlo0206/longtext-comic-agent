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
    DENIAL = "DENIAL"
    ACCUSATION = "ACCUSATION"
    HYPOTHESIS = "HYPOTHESIS"
    MEMORY = "MEMORY"
    INTERPRETATION = "INTERPRETATION"
    PREDICTION = "PREDICTION"


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


class EventProposalV1(StrictBaseModel):
    """Candidate story event discovered from source text."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    event_type: str = Field(description="Event type label.")
    summary: str = Field(description="Faithful event summary.")
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
        description="Source evidence references.",
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


class ClaimProposalV1(StrictBaseModel):
    """Candidate claim, statement, denial, memory, or interpretation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    proposal_id: str = Field(description="Proposal id.")
    claim_type: ClaimType = Field(description="Claim type.")
    claim_text: str = Field(description="Exact or faithful claim text.")
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

    @field_validator("claim_text")
    @classmethod
    def claim_text_not_blank(cls, value: str) -> str:
        """Reject empty claim text."""

        if value.strip() == "":
            raise ValueError("claim_text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ClaimProposalV1":
        """Avoid binding a known source id to an explicitly unknown source."""

        if self.source_type == ClaimSourceType.UNKNOWN and self.source_id is not None:
            raise ValueError("UNKNOWN claim source cannot include source_id")
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
