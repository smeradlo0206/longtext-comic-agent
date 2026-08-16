from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .config import EDIT_MODEL_ID, RENDER_PROFILES


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RenderProfile(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class SceneJobStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PLANNING = "PLANNING"
    CONDITIONING = "CONDITIONING"
    GENERATING = "GENERATING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


TERMINAL_SCENE_STATUSES = {
    SceneJobStatus.SUCCEEDED,
    SceneJobStatus.PARTIAL_FAILED,
    SceneJobStatus.FAILED,
}


class PanelJobStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PLANNED = "PLANNED"
    CONDITIONED = "CONDITIONED"
    GENERATING = "GENERATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SceneContextV1(StrictModel):
    summary: ShortText
    location: ShortText
    time_of_day: ShortText | None = None
    atmosphere: ShortText | None = None
    continuity_notes: list[ShortText] = Field(default_factory=list, max_length=64)


class CharacterIntentV1(StrictModel):
    character_id: Identifier
    action: ShortText
    emotion: ShortText


class DialogueV1(StrictModel):
    speaker_id: Identifier
    text: ShortText


class PanelIntentV1(StrictModel):
    panel_id: Identifier
    sequence_no: int = Field(ge=0)
    story_intent: ShortText
    characters: list[CharacterIntentV1] = Field(default_factory=list, max_length=2)
    dialogue: list[DialogueV1] = Field(default_factory=list, max_length=16)
    constraints: list[ShortText] = Field(default_factory=list, max_length=32)
    render_profile: RenderProfile = RenderProfile.LANDSCAPE

    @field_validator("characters")
    @classmethod
    def unique_characters(cls, value: list[CharacterIntentV1]) -> list[CharacterIntentV1]:
        ids = [item.character_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("panel character_ids must be unique")
        return value


class SceneJobV1(StrictModel):
    schema_name: Literal["SceneJobV1"] = "SceneJobV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    project_id: Identifier
    chapter_id: Identifier
    scene_id: Identifier
    asset_profile_id: Identifier
    scene_context: SceneContextV1
    panels: list[PanelIntentV1] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_panel_identity(self) -> "SceneJobV1":
        panel_ids = [panel.panel_id for panel in self.panels]
        sequence = [panel.sequence_no for panel in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("panel_ids must be unique")
        if len(sequence) != len(set(sequence)):
            raise ValueError("panel sequence_no values must be unique")
        return self


class RegionV1(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_canvas(self) -> "RegionV1":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("region must stay inside normalized canvas")
        return self


class CharacterVisualStateV1(StrictModel):
    character_id: Identifier
    placement: Literal["left", "center", "right", "background"]
    action: ShortText
    expression: ShortText
    gaze: ShortText


class AssetBindingV1(StrictModel):
    asset_id: Identifier
    purpose: Literal["identity", "scene", "style"]
    target_character_id: Identifier | None = None
    image_index: int = Field(ge=1, le=3)


class PanelVisualPlanV1(StrictModel):
    panel_id: Identifier
    narrative_focus: ShortText
    emotional_target: ShortText
    shot_size: Literal["extreme_wide", "wide", "medium", "close_up", "extreme_close_up"]
    camera_angle: Literal["eye_level", "high", "low", "over_shoulder", "top_down", "dutch"]
    camera_direction: ShortText
    characters: list[CharacterVisualStateV1] = Field(default_factory=list, max_length=2)
    foreground: list[ShortText] = Field(default_factory=list, max_length=8)
    midground: list[ShortText] = Field(default_factory=list, max_length=8)
    background: list[ShortText] = Field(default_factory=list, max_length=8)
    focal_point: ShortText
    environment: ShortText
    lighting: ShortText
    atmosphere: ShortText
    dialogue_safe_zones: list[RegionV1] = Field(default_factory=list, max_length=4)
    asset_bindings: list[AssetBindingV1] = Field(default_factory=list, max_length=3)
    required_elements: list[ShortText] = Field(default_factory=list, max_length=16)
    forbidden_elements: list[ShortText] = Field(default_factory=list, max_length=16)


class VisualPlanV1(StrictModel):
    schema_name: Literal["VisualPlanV1"] = "VisualPlanV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    planner_model_id: str
    panels: list[PanelVisualPlanV1] = Field(min_length=1, max_length=32)


class ReferenceInputV1(StrictModel):
    asset_id: Identifier
    purpose: Literal["identity", "scene", "style"]
    image_index: int = Field(ge=1, le=3)
    uri: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_character_id: Identifier | None = None


class GenerationSpecV1(StrictModel):
    schema_name: Literal["GenerationSpecV1"] = "GenerationSpecV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    panel_id: Identifier
    prompt_id: Identifier
    positive_prompt: str = Field(min_length=1, max_length=16000)
    negative_prompt: str = Field(min_length=1, max_length=8000)
    references: list[ReferenceInputV1] = Field(min_length=1, max_length=3)
    render_profile: RenderProfile
    width: int
    height: int
    seed: int = Field(ge=0)
    steps: Literal[50] = 50
    true_cfg_scale: Literal[4.0] = 4.0
    guidance_scale: Literal[1.0] = 1.0
    max_sequence_length: Literal[1024] = 1024
    model_id: Literal[EDIT_MODEL_ID] = EDIT_MODEL_ID
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    used_asset_ids: list[Identifier] = Field(min_length=1, max_length=3)
    visual_plan_version: Literal["1.0"] = "1.0"

    @model_validator(mode="after")
    def profile_size_matches(self) -> "GenerationSpecV1":
        if (self.width, self.height) != RENDER_PROFILES[self.render_profile.value]:
            raise ValueError("width and height do not match render_profile")
        return self


class SceneErrorV1(StrictModel):
    code: str
    message: str
    retryable: bool = False


class PanelArtifactV1(StrictModel):
    image_id: Identifier
    uri: str
    url: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: Literal["image/png"] = "image/png"


class PanelGenerationMetadataV1(StrictModel):
    model_id: str
    model_revision: str
    seed: int
    attempt: int = Field(ge=1, le=3)
    worker_id: str
    gpu_ids: list[int]
    generation_seconds: float = Field(ge=0)
    completed_at: datetime


class PanelGenerationResultV1(StrictModel):
    panel_id: Identifier
    status: PanelJobStatus
    visual_plan: PanelVisualPlanV1 | None = None
    generation_spec: GenerationSpecV1 | None = None
    artifact: PanelArtifactV1 | None = None
    metadata: PanelGenerationMetadataV1 | None = None
    error: SceneErrorV1 | None = None


class SceneResultV1(StrictModel):
    schema_name: Literal["SceneResultV1"] = "SceneResultV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    project_id: Identifier
    chapter_id: Identifier
    scene_id: Identifier
    status: SceneJobStatus
    panels: list[PanelGenerationResultV1]
    generation_revision: Literal[1] = 1
    evaluation_status: Literal["NOT_RUN"] = "NOT_RUN"
    submitted_at: datetime
    completed_at: datetime | None = None


class EvaluationPort(Protocol):
    def evaluate(self, result: PanelGenerationResultV1) -> object: ...


class RegenerationPort(Protocol):
    def regenerate(self, original: PanelGenerationResultV1, instruction: object) -> str: ...


def canonical_scene_bytes(job: SceneJobV1) -> bytes:
    payload = job.model_dump(mode="json")
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def scene_job_sha256(job: SceneJobV1) -> str:
    return hashlib.sha256(canonical_scene_bytes(job)).hexdigest()


def panel_seed(request_id: str, panel_id: str) -> int:
    digest = hashlib.sha256(f"{request_id}:{panel_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF
