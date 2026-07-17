"""Source document, project, chapter, and chunk schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import StrictBaseModel


class ProjectType(StrEnum):
    """Supported project input families."""

    LONG_NOVEL = "LONG_NOVEL"
    CAMPUS_NEWS = "CAMPUS_NEWS"
    PROMOTION = "PROMOTION"
    NOTICE = "NOTICE"


class FidelityMode(StrEnum):
    """Top-level fidelity policy mode."""

    CANON_STRICT = "CANON_STRICT"
    FACT_STRICT = "FACT_STRICT"
    CREATIVE_AUTHORIZED = "CREATIVE_AUTHORIZED"


class ProjectSpecV1(StrictBaseModel):
    """Project-level constraints that all agents must obey."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    id: str = Field(description="Project id.", examples=["project-1"])
    name: str = Field(description="Human readable project name.", examples=["Golden Novel"])
    project_type: ProjectType = Field(description="Input project type.")
    fidelity_mode: FidelityMode = Field(description="Fidelity policy mode.")
    output_format: str = Field(
        description="Output format such as PAGES or STRIP.",
        examples=["PAGES"],
    )
    reading_direction: str = Field(description="Reading direction.", examples=["LTR", "RTL"])
    allow_new_events: bool = Field(description="Whether agents may invent new events.")
    allow_new_dialogue: bool = Field(description="Whether agents may invent dialogue.")
    allow_event_reordering: bool = Field(description="Whether event order may change.")
    allow_visual_compression: bool = Field(
        description="Whether visuals may compress source detail."
    )
    allow_dialogue_splitting: bool = Field(
        description="Whether dialogue may be split across panels."
    )
    require_source_traceability: bool = Field(description="Whether facts must cite source chunks.")
    max_auto_repairs: int = Field(ge=0, description="Maximum automatic repair attempts.")
    budget_limit: float | None = Field(
        default=None,
        ge=0,
        description="Optional cost budget limit.",
    )


class SourceDocumentV1(StrictBaseModel):
    """Imported source file metadata."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    document_id: str = Field(description="Stable source document id.")
    project_id: str = Field(description="Owning project id.")
    filename: str = Field(description="Original filename.")
    mime_type: str = Field(description="Detected or uploaded MIME type.")
    checksum: str = Field(description="SHA-256 checksum of source bytes.")
    storage_uri: str = Field(description="URI for original source object.")
    imported_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Import timestamp in UTC.",
    )
    revision: int = Field(default=1, ge=1, description="Document revision.")


class SourceChapterV1(StrictBaseModel):
    """Chapter boundary derived from source text."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    chapter_id: str = Field(description="Stable chapter id.")
    document_id: str = Field(description="Source document id.")
    project_id: str = Field(description="Owning project id.")
    title: str = Field(description="Chapter title or generated default.")
    order: int = Field(ge=0, description="Zero-based chapter order.")
    start_chunk_order: int = Field(ge=0, description="First chunk order in this chapter.")
    end_chunk_order: int = Field(ge=0, description="Last chunk order in this chapter.")

    @model_validator(mode="after")
    def validate_chunk_range(self) -> "SourceChapterV1":
        """Ensure chapter chunk order range is coherent."""

        if self.end_chunk_order < self.start_chunk_order:
            raise ValueError("end_chunk_order must be >= start_chunk_order")
        return self


class SourceChunkV1(StrictBaseModel):
    """Minimal traceable unit of source text."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    chunk_id: str = Field(description="Stable source chunk id.")
    document_id: str = Field(description="Source document id.")
    chapter_id: str = Field(description="Owning chapter id.")
    project_id: str = Field(description="Owning project id.")
    order: int = Field(ge=0, description="Zero-based chunk order within the document.")
    text: str = Field(description="Exact source text for this chunk.")
    source_page: int | None = Field(default=None, ge=1, description="Optional source page number.")
    char_start: int | None = Field(default=None, ge=0, description="Start char offset in source.")
    char_end: int | None = Field(
        default=None,
        ge=0,
        description="Exclusive end char offset in source.",
    )
    checksum: str = Field(description="SHA-256 checksum of chunk text.")

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        """Reject empty chunks."""

        if value == "":
            raise ValueError("text must not be empty")
        return value

    @model_validator(mode="after")
    def validate_char_range(self) -> "SourceChunkV1":
        """Ensure character offsets are either omitted or valid."""

        start_exists = self.char_start is not None
        end_exists = self.char_end is not None
        if start_exists != end_exists:
            raise ValueError("char_start and char_end must be provided together")
        if self.char_start is not None and self.char_end is not None:
            if self.char_end <= self.char_start:
                raise ValueError("char_end must be greater than char_start")
        return self
