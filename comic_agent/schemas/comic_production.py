"""Contracts for source-grounded long-text comic production."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel
from comic_agent.schemas.image_workflow import (
    GenerationSettings,
    ReferenceLibraryPolicy,
    SelectedAsset,
    VisualQASettings,
    WorkflowJob,
)
from comic_agent.schemas.production import PromptSpecV1
from comic_agent.schemas.visual import PageSpecV1, PanelSpecV1


class ComicPlannerMode(StrEnum):
    """Supported story-to-panel planning implementations."""

    DETERMINISTIC_EXTRACTIVE = "DETERMINISTIC_EXTRACTIVE"
    LLM_PROPOSAL = "LLM_PROPOSAL"


class IdentityAnchorMode(StrEnum):
    """Whether panel generation first normalizes character references to color anchors."""

    OFF = "OFF"
    AUTO = "AUTO"


class ComicRunStatus(StrEnum):
    """Lifecycle states for an auditable comic production run."""

    COMPILED = "COMPILED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DialogueLayoutSettingsV1(StrictBaseModel):
    """Deterministic post-generation lettering configuration."""

    enabled: bool = False
    font_path: str | None = None
    min_font_size: int = Field(default=18, ge=10, le=96)
    max_font_size: int = Field(default=32, ge=10, le=128)
    bubble_padding: int = Field(default=18, ge=4, le=64)
    max_bubble_width_ratio: float = Field(default=0.38, ge=0.2, le=0.8)

    @model_validator(mode="after")
    def validate_font_range(self) -> "DialogueLayoutSettingsV1":
        if self.max_font_size < self.min_font_size:
            raise ValueError("max_font_size must be at least min_font_size")
        return self


class ComicStageTimingsV1(StrictBaseModel):
    """Diagnostic latency stages recorded by the workflow."""

    setup: float = Field(default=0.0, ge=0.0)
    reference_copy: float = Field(default=0.0, ge=0.0)
    model_load: float = Field(default=0.0, ge=0.0)
    identity_anchor_generation: float = Field(default=0.0, ge=0.0)
    panel_generation: float = Field(default=0.0, ge=0.0)
    visual_qa: float = Field(default=0.0, ge=0.0)
    selective_repair_generation: float = Field(default=0.0, ge=0.0)
    contact_sheet: float = Field(default=0.0, ge=0.0)
    page_composition: float = Field(default=0.0, ge=0.0)
    lettering: float = Field(default=0.0, ge=0.0)


class ComicPerformanceV1(StrictBaseModel):
    """Latency budget report exposed by CLI and API production runs."""

    latency_budget_seconds: float = Field(gt=0.0)
    queue_wait_seconds: float = Field(ge=0.0)
    backend_reused: bool
    stages: ComicStageTimingsV1
    workflow_seconds: float | None = Field(default=None, ge=0.0)
    end_to_end_seconds: float | None = Field(default=None, ge=0.0)
    single_image_seconds: float | None = Field(default=None, ge=0.0)
    within_budget: bool | None = None
    workflow_within_budget: bool | None = None


class ComicProductionRequestV1(StrictBaseModel):
    """Locked user input for adapting imported source text into comic pages."""

    schema_version: Literal["1.0"] = "1.0"
    document_id: str = Field(description="Imported source document id.")
    chapter_ids: list[str] = Field(
        default_factory=list,
        description="Optional source chapters; an empty list selects the document.",
    )
    planner_mode: ComicPlannerMode = ComicPlannerMode.DETERMINISTIC_EXTRACTIVE
    panels_per_page: int = Field(default=6, ge=1, le=6)
    max_pages: int = Field(default=2, ge=1, le=20)
    comic_style: str = Field(min_length=3, max_length=1000)
    global_prompt: str = Field(min_length=1, max_length=12000)
    quality_constraints: list[str] = Field(default_factory=list, max_length=20)
    selected_assets: list[SelectedAsset] = Field(min_length=1, max_length=3)
    reference_policy: ReferenceLibraryPolicy = Field(default_factory=ReferenceLibraryPolicy)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    visual_qa: VisualQASettings = Field(default_factory=VisualQASettings)
    dialogue_layout: DialogueLayoutSettingsV1 = Field(
        default_factory=DialogueLayoutSettingsV1
    )
    continuity_enabled: bool = True
    identity_anchor_mode: IdentityAnchorMode = IdentityAnchorMode.OFF


class ComicPanelProposalV1(StrictBaseModel):
    """Proposal-only visual translation of one exact source excerpt."""

    schema_version: Literal["1.0"] = "1.0"
    panel: PanelSpecV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    visual_expression: str = Field(min_length=1)
    continuity_parent_panel_id: str | None = None

    @model_validator(mode="after")
    def evidence_matches_panel(self) -> "ComicPanelProposalV1":
        evidence_chunk_ids = {item.chunk_id for item in self.evidence_refs}
        if not evidence_chunk_ids.issubset(set(self.panel.source_chunk_ids)):
            raise ValueError("panel evidence must reference panel source chunks")
        if any(item.text not in self.source_quote for item in self.panel.text_overlays):
            raise ValueError("panel text overlays must be exact substrings of source_quote")
        return self


class ComicStoryboardProposalV1(StrictBaseModel):
    """Proposal-only page and panel plan derived from bounded source context."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str
    project_id: str
    document_id: str
    planner_id: str
    source_chunk_ids: list[str] = Field(min_length=1)
    pages: list[PageSpecV1] = Field(min_length=1, max_length=20)
    panels: list[ComicPanelProposalV1] = Field(min_length=1, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_page_panel_graph(self) -> "ComicStoryboardProposalV1":
        panel_ids = [item.panel.panel_id for item in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("comic panel ids must be unique")
        page_ids = [item.page_id for item in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("comic page ids must be unique")
        planned = [panel_id for page in self.pages for panel_id in page.panel_ids]
        if planned != panel_ids:
            raise ValueError("page panel order must exactly match proposal panels")
        allowed_chunks = set(self.source_chunk_ids)
        if any(
            not set(item.panel.source_chunk_ids).issubset(allowed_chunks)
            for item in self.panels
        ):
            raise ValueError("panel references a chunk outside proposal source scope")
        return self


class ComicProductionManifestV1(StrictBaseModel):
    """Immutable handoff from an approved storyboard proposal to image execution."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    project_id: str
    request_hash: str
    request: ComicProductionRequestV1
    proposal: ComicStoryboardProposalV1
    prompt_specs: list[PromptSpecV1] = Field(min_length=1, max_length=120)
    workflow_job: WorkflowJob
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_handoff(self) -> "ComicProductionManifestV1":
        panel_ids = [item.panel.panel_id for item in self.proposal.panels]
        if [item.panel_id for item in self.prompt_specs] != panel_ids:
            raise ValueError("prompt specs must preserve proposal panel order")
        if [item.shot_id for item in self.workflow_job.shots] != panel_ids:
            raise ValueError("image workflow must preserve proposal panel order")
        return self


class ComicPageArtifactV1(StrictBaseModel):
    """Rendered page artifact and its panel membership."""

    schema_version: Literal["1.0"] = "1.0"
    page_id: str
    order: int = Field(ge=0)
    panel_ids: list[str] = Field(min_length=1, max_length=6)
    file: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ComicProductionRunV1(StrictBaseModel):
    """Persistent status and artifacts for one idempotent production run."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    project_id: str
    document_id: str
    request_hash: str
    status: ComicRunStatus
    manifest: ComicProductionManifestV1
    queue_id: str | None = None
    run_root: str | None = None
    page_artifacts: list[ComicPageArtifactV1] = Field(default_factory=list)
    performance: ComicPerformanceV1 | None = None
    error: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
