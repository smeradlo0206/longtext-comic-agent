"""Narrative extraction proposal schemas."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

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
    location_id: str | None = Field(default=None, description="Location entity id if known.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1,
        description="Source evidence references.",
    )
    confidence: float = Field(ge=0, le=1, description="Agent confidence.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")


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
