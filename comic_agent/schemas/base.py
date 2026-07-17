"""Shared schema primitives for all agents and services."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictBaseModel(BaseModel):
    """Base model that rejects undeclared fields across V1 contracts."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class RecordStatus(StrEnum):
    """Lifecycle status for versioned records."""

    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    CANONICAL = "CANONICAL"
    APPROVED = "APPROVED"
    STALE = "STALE"
    REJECTED = "REJECTED"


class RealityLayer(StrEnum):
    """Narrative reality layer for facts and visual/story specs."""

    PRIMARY = "PRIMARY"
    FLASHBACK = "FLASHBACK"
    INSERT = "INSERT"
    DREAM = "DREAM"
    IMAGINED = "IMAGINED"
    HYPOTHETICAL = "HYPOTHETICAL"
    UNKNOWN = "UNKNOWN"


class BaseRecordV1(StrictBaseModel):
    """Common metadata for canonical and candidate records."""

    id: str = Field(description="Stable record identifier.", examples=["record-1"])
    project_id: str = Field(description="Owning project identifier.", examples=["project-1"])
    schema_version: Literal["1.0"] = Field(
        default="1.0", description="Schema contract version.", examples=["1.0"]
    )
    revision: int = Field(ge=1, description="Monotonic record revision.", examples=[1])
    status: RecordStatus = Field(description="Record lifecycle status.", examples=["CANONICAL"])
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp in UTC.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp in UTC.",
    )
    created_by: str = Field(description="Creator service or agent id.", examples=["importer"])


class EvidenceRefV1(StrictBaseModel):
    """Pointer from a derived fact back to exact source text."""

    chunk_id: str = Field(description="Referenced SourceChunk id.", examples=["chunk-1"])
    quote_start: int | None = Field(
        default=None,
        ge=0,
        description="Optional start offset inside SourceChunk text.",
        examples=[0],
    )
    quote_end: int | None = Field(
        default=None,
        description="Optional exclusive end offset inside SourceChunk text.",
        examples=[8],
    )
    quote_text: str | None = Field(
        default=None,
        description="Optional copied quote used by reviewers for quick inspection.",
        examples=["递给她"],
    )

    @field_validator("quote_text")
    @classmethod
    def quote_text_not_blank(cls, value: str | None) -> str | None:
        """Reject empty quote text while allowing omitted quotes."""

        if value is not None and value == "":
            raise ValueError("quote_text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_range_pair(self) -> "EvidenceRefV1":
        """Ensure quote offsets are present as a valid pair."""

        start_exists = self.quote_start is not None
        end_exists = self.quote_end is not None
        if start_exists != end_exists:
            raise ValueError("quote_start and quote_end must be provided together")
        if self.quote_start is not None and self.quote_end is not None:
            if self.quote_end <= self.quote_start:
                raise ValueError("quote_end must be greater than quote_start")
        return self
