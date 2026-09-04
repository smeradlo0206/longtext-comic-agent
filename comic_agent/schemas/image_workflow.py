from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from comic_agent.schemas.base import StrictBaseModel

MODEL_ID: Literal["black-forest-labs/FLUX.2-klein-4B"] = (
    "black-forest-labs/FLUX.2-klein-4B"
)
ASSET_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
ENTITY_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
SLOT_PATTERN = r"^[A-Z][A-Z0-9_]{1,31}$"

ReferenceRole = Literal[
    "character_identity",
    "character_outfit",
    "scene",
    "prop",
    "style",
    "composition",
    "continuity",
]

ReferenceLifecycle = Literal["candidate", "approved", "rejected"]
ReferencePolicyMode = Literal["DIRECT", "APPROVED_LIBRARY"]


class StrictModel(StrictBaseModel):
    """Immutable contracts used by the local image workflow."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )


class ReferenceImage(StrictModel):
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    filename: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bytes: int = Field(gt=0)
    lifecycle: ReferenceLifecycle = "candidate"
    entity_id: str | None = Field(default=None, pattern=ENTITY_ID_PATTERN)
    intended_role: ReferenceRole | None = None
    variant: str = Field(default="base", min_length=1, max_length=100)
    is_canonical: bool = False
    approved_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_library_metadata(self) -> ReferenceImage:
        if self.is_canonical and self.lifecycle != "approved":
            raise ValueError("canonical references must be approved")
        if self.is_canonical and (self.entity_id is None or self.intended_role is None):
            raise ValueError("canonical references require entity_id and intended_role")
        if self.lifecycle == "approved" and self.approved_at is None:
            raise ValueError("approved references require approved_at")
        if self.lifecycle != "approved" and self.approved_at is not None:
            raise ValueError("only approved references may have approved_at")
        return self


class ReferenceCatalog(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    references: list[ReferenceImage] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_entries(self) -> ReferenceCatalog:
        ids = [item.asset_id for item in self.references]
        paths = [item.relative_path for item in self.references]
        if len(ids) != len(set(ids)):
            raise ValueError("reference asset IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("reference paths must be unique")
        canonical_bindings = [
            (item.entity_id, item.intended_role)
            for item in self.references
            if item.is_canonical
        ]
        if len(canonical_bindings) != len(set(canonical_bindings)):
            raise ValueError("an entity and role can have at most one canonical reference")
        return self


class ReferenceLibraryPolicy(StrictModel):
    """How selected assets are admitted into an image workflow."""

    mode: ReferencePolicyMode = "DIRECT"
    require_canonical: bool = True


class SelectedAsset(StrictModel):
    slot: str = Field(pattern=SLOT_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    entity_id: str = Field(pattern=ENTITY_ID_PATTERN)
    role: ReferenceRole
    description: str = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


def validate_unique_selections(value: list[SelectedAsset]) -> list[SelectedAsset]:
    slots = [item.slot for item in value]
    asset_ids = [item.asset_id for item in value]
    if len(slots) != len(set(slots)):
        raise ValueError("selected asset slots must be unique")
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("selected asset IDs must be unique")
    return value


class StoryboardRequest(StrictModel):
    schema_version: Literal["2.0", "2.1", "2.2"] = "2.2"
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    script: str = Field(min_length=1, max_length=120000)
    comic_style: str = Field(min_length=3, max_length=1000)
    global_prompt: str = Field(min_length=1, max_length=12000)
    quality_constraints: list[str] = Field(default_factory=list, max_length=20)
    selected_assets: list[SelectedAsset] = Field(min_length=1, max_length=64)

    @field_validator("selected_assets")
    @classmethod
    def unique_selected_assets(cls, value: list[SelectedAsset]) -> list[SelectedAsset]:
        return validate_unique_selections(value)


class ShotReference(StrictModel):
    slot: str = Field(pattern=SLOT_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    role: ReferenceRole
    purpose: str = Field(min_length=1, max_length=500)


class ContinuityCrop(StrictModel):
    left: float = Field(ge=0.0, le=1.0)
    top: float = Field(ge=0.0, le=1.0)
    right: float = Field(ge=0.0, le=1.0)
    bottom: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_area(self) -> ContinuityCrop:
        if self.right - self.left < 0.05 or self.bottom - self.top < 0.05:
            raise ValueError("continuity crop width and height must be at least 0.05")
        return self


class Shot(StrictModel):
    shot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    prompt: str = Field(min_length=1, max_length=12000)
    references: list[ShotReference] = Field(default_factory=list, max_length=4)
    continuity_from: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    continuity_crop: ContinuityCrop | None = None
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    @field_validator("references")
    @classmethod
    def unique_references(cls, value: list[ShotReference]) -> list[ShotReference]:
        slots = [item.slot for item in value]
        asset_ids = [item.asset_id for item in value]
        if len(slots) != len(set(slots)):
            raise ValueError("a shot cannot use the same asset slot twice")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("a shot cannot use the same asset twice")
        return value

    @model_validator(mode="after")
    def crop_requires_source(self) -> Shot:
        if self.continuity_crop is not None and self.continuity_from is None:
            raise ValueError("continuity_crop requires continuity_from")
        return self


class GenerationSettings(StrictModel):
    model_id: Literal["black-forest-labs/FLUX.2-klein-4B"] = MODEL_ID
    width: int = Field(default=1664, ge=256, le=4096)
    height: int = Field(default=928, ge=256, le=4096)
    steps: int = Field(default=4, ge=1, le=50)
    guidance_scale: float = Field(default=1.0, ge=0.0, le=20.0)
    seed: int = Field(default=2026082101, ge=0, le=2**63 - 1)
    attempts: int = Field(default=2, ge=1, le=3)
    device: str = Field(default="cuda:0", pattern=r"^cuda(?::[0-9]+)?$")
    dtype: Literal["bfloat16"] = "bfloat16"

    @field_validator("width", "height")
    @classmethod
    def divisible_by_sixteen(cls, value: int) -> int:
        if value % 16:
            raise ValueError("image dimensions must be divisible by 16")
        return value


class VisualQASettings(StrictModel):
    """Fast local visual checks and bounded selective repair settings."""

    enabled: bool = False
    latency_budget_seconds: float = Field(default=60.0, gt=0.0, le=3600.0)
    min_dynamic_range: float = Field(default=0.12, ge=0.0, le=1.0)
    min_edge_energy: float = Field(default=0.015, ge=0.0, le=1.0)
    min_reference_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    max_auto_repairs: int = Field(default=1, ge=0, le=3)


class IdentityAnchorSpec(StrictModel):
    """One generated color reference shared by every panel containing an entity."""

    anchor_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    slot: str = Field(pattern=SLOT_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    entity_id: str = Field(pattern=ENTITY_ID_PATTERN)
    description: str = Field(min_length=1, max_length=500)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(default=768, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)

    @field_validator("width", "height")
    @classmethod
    def divisible_by_sixteen(cls, value: int) -> int:
        if value % 16:
            raise ValueError("identity anchor dimensions must be divisible by 16")
        return value


class ContactSheetSettings(StrictModel):
    columns: int = Field(default=3, ge=1, le=10)
    filename: str = Field(
        default="storyboard-contact-sheet.png",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.png$",
    )


class WorkflowJob(StrictModel):
    schema_version: Literal["2.0", "2.1", "2.2"] = "2.2"
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    source_script: str = Field(min_length=1, max_length=120000)
    comic_style: str = Field(min_length=3, max_length=1000)
    global_prompt: str = Field(min_length=1, max_length=12000)
    quality_constraints: list[str] = Field(default_factory=list, max_length=20)
    selected_assets: list[SelectedAsset] = Field(min_length=1, max_length=64)
    reference_policy: ReferenceLibraryPolicy = Field(default_factory=ReferenceLibraryPolicy)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    visual_qa: VisualQASettings = Field(default_factory=VisualQASettings)
    identity_anchors: list[IdentityAnchorSpec] = Field(default_factory=list, max_length=16)
    contact_sheet: ContactSheetSettings | None = None
    shots: list[Shot] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_storyboard(self) -> WorkflowJob:
        validate_unique_selections(self.selected_assets)
        shot_ids = [item.shot_id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot IDs must be unique")

        anchor_ids = [item.anchor_id for item in self.identity_anchors]
        anchor_entities = [item.entity_id for item in self.identity_anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("identity anchor IDs must be unique")
        if len(anchor_entities) != len(set(anchor_entities)):
            raise ValueError("an entity can have at most one identity anchor")

        selected = {
            (item.slot, item.asset_id, item.role)
            for item in self.selected_assets
        }
        selected_by_asset_id = {item.asset_id: item for item in self.selected_assets}
        for anchor in self.identity_anchors:
            source = selected_by_asset_id.get(anchor.asset_id)
            if source is None:
                raise ValueError(
                    f"identity anchor {anchor.anchor_id} uses an unselected asset"
                )
            if source.role not in {"character_identity", "character_outfit"}:
                raise ValueError(
                    f"identity anchor {anchor.anchor_id} requires a character asset"
                )
            if (source.slot, source.entity_id) != (anchor.slot, anchor.entity_id):
                raise ValueError(
                    f"identity anchor {anchor.anchor_id} does not match its selected asset"
                )
        for shot in self.shots:
            invalid = [
                reference
                for reference in shot.references
                if (reference.slot, reference.asset_id, reference.role) not in selected
            ]
            if invalid:
                labels = [
                    f"{item.slot}:{item.asset_id}:{item.role}"
                    for item in invalid
                ]
                raise ValueError(
                    f"shot {shot.shot_id} uses references outside selected_assets: {labels}"
                )
        return self


class PlannedReference(StrictModel):
    image_index: int = Field(ge=1, le=4)
    slot: str = Field(pattern=SLOT_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    entity_id: str = Field(pattern=ENTITY_ID_PATTERN)
    role: ReferenceRole
    purpose: str
    path: Path


class PlannedIdentityAnchor(StrictModel):
    """Resolved identity normalization task executed before panel generation."""

    anchor_id: str
    slot: str = Field(pattern=SLOT_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    entity_id: str = Field(pattern=ENTITY_ID_PATTERN)
    prompt: str = Field(min_length=1, max_length=12000)
    source_reference: PlannedReference
    seed: int
    width: int
    height: int

    @model_validator(mode="after")
    def source_matches_anchor(self) -> PlannedIdentityAnchor:
        source = self.source_reference
        if (source.slot, source.asset_id, source.entity_id) != (
            self.slot,
            self.asset_id,
            self.entity_id,
        ):
            raise ValueError("planned identity anchor source does not match its binding")
        return self


class PlannedShot(StrictModel):
    shot_id: str
    prompt: str
    references: list[PlannedReference] = Field(default_factory=list, max_length=4)
    continuity_from: str | None = None
    continuity_crop: ContinuityCrop | None = None
    continuity_image_index: int | None = Field(default=None, ge=1, le=4)
    seed: int


class WorkflowPlan(StrictModel):
    job_id: str
    model_id: Literal["black-forest-labs/FLUX.2-klein-4B"]
    identity_anchors: list[PlannedIdentityAnchor] = Field(default_factory=list)
    shots: list[PlannedShot]
    execution_order: list[str]
    contact_sheet: ContactSheetSettings | None = None


QueueStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
AttemptStatus = Literal["succeeded", "failed", "interrupted"]


class QueueAttempt(StrictModel):
    """One auditable execution attempt for a queued image workflow."""

    attempt: int = Field(ge=1)
    worker_id: str = Field(min_length=1, max_length=200)
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime
    run_root: str | None = None
    error: str | None = Field(default=None, max_length=4000)


class QueueItem(StrictModel):
    """Persistent file-queue record for one image workflow."""

    schema_version: Literal["1.0"] = "1.0"
    queue_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    status: QueueStatus
    priority: int = Field(default=100, ge=0, le=1000)
    enqueued_at: datetime
    updated_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    worker_id: str | None = Field(default=None, max_length=200)
    handoff_validated: bool = False
    attempts: int = Field(default=0, ge=0)
    run_root: str | None = None
    error: str | None = Field(default=None, max_length=4000)
    history: list[QueueAttempt] = Field(default_factory=list)
    job: WorkflowJob

    @model_validator(mode="after")
    def queue_id_matches_job(self) -> QueueItem:
        if self.queue_id != self.job.job_id:
            raise ValueError("queue_id must equal job.job_id")
        return self
