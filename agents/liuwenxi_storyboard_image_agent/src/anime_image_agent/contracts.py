from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .config import RENDER_PROFILE


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
Revision = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PanelSpecV1(StrictModel):
    schema_name: Literal["PanelSpecV1"] = "PanelSpecV1"
    shot_type: ShortText
    camera: ShortText
    composition: ShortText
    character_ids: list[Identifier] = Field(default_factory=list, max_length=32)
    action: ShortText
    scene: ShortText
    continuity_notes: list[ShortText] = Field(default_factory=list, max_length=64)

    @field_validator("character_ids")
    @classmethod
    def character_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("character_ids must be unique")
        return value


class PromptSpecV1(StrictModel):
    schema_name: Literal["PromptSpecV1"] = "PromptSpecV1"
    prompt_id: Identifier
    language: Literal["zh-CN"] = "zh-CN"
    positive_prompt: PromptText
    negative_prompt: str = Field(default="", max_length=8000)
    story_bible_revision: Revision
    scene_plan_revision: Revision

    @field_validator("negative_prompt")
    @classmethod
    def normalize_negative_prompt(cls, value: str) -> str:
        return value.strip()


class ImageJobV1(StrictModel):
    schema_name: Literal["ImageJobV1"] = "ImageJobV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    project_id: Identifier
    chapter_id: Identifier
    scene_id: Identifier
    panel_id: Identifier
    sequence_no: int = Field(ge=0)
    render_profile: Literal[RENDER_PROFILE] = RENDER_PROFILE
    panel_spec: PanelSpecV1
    prompt_spec: PromptSpecV1
    retry_of: Identifier | None = None

    @model_validator(mode="after")
    def retry_cannot_reference_itself(self) -> "ImageJobV1":
        if self.retry_of == self.request_id:
            raise ValueError("retry_of cannot equal request_id")
        return self


class ResultStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class ArtifactV1(StrictModel):
    uri: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["image/png"] = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bytes: int = Field(gt=0)
    pixel_variance: list[float] = Field(min_length=3, max_length=3)


class GenerationMetadataV1(StrictModel):
    model_id: str
    model_revision: str
    render_profile: Literal[RENDER_PROFILE] = RENDER_PROFILE
    dtype: Literal["bfloat16"] = "bfloat16"
    scheduler: str
    seed: int = Field(ge=0)
    attempt: int = Field(ge=1, le=3)
    width: Literal[1664] = 1664
    height: Literal[928] = 928
    steps: Literal[50] = 50
    true_cfg_scale: Literal[4.0] = 4.0
    max_sequence_length: Literal[512] = 512
    gpu_ids: list[int] = Field(min_length=2, max_length=2)
    worker_id: str
    model_load_seconds: float = Field(ge=0)
    generation_seconds: float = Field(ge=0)
    peak_vram_gib: list[float] = Field(min_length=2, max_length=2)
    positive_token_count: int = Field(gt=0, le=512)
    negative_token_count: int = Field(gt=0, le=512)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    started_at: datetime
    completed_at: datetime

    @field_validator("gpu_ids")
    @classmethod
    def gpu_ids_must_be_distinct(cls, value: list[int]) -> list[int]:
        if len(set(value)) != 2:
            raise ValueError("gpu_ids must contain two distinct devices")
        return value


class GeneratedImageV1(StrictModel):
    schema_name: Literal["GeneratedImageV1"] = "GeneratedImageV1"
    image_id: Identifier
    prompt_id: Identifier
    artifact: ArtifactV1
    metadata: GenerationMetadataV1


class ImageErrorV1(StrictModel):
    code: Identifier
    message: str = Field(min_length=1, max_length=2048)
    retryable: bool


class ImageResultV1(StrictModel):
    schema_name: Literal["ImageResultV1"] = "ImageResultV1"
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identifier
    project_id: Identifier
    chapter_id: Identifier
    scene_id: Identifier
    panel_id: Identifier
    sequence_no: int = Field(ge=0)
    status: ResultStatus
    attempts: int = Field(ge=0, le=3)
    generated_image: GeneratedImageV1 | None = None
    error: ImageErrorV1 | None = None
    completed_at: datetime

    @model_validator(mode="after")
    def status_payload_must_match(self) -> "ImageResultV1":
        if self.status == ResultStatus.SUCCEEDED:
            if self.generated_image is None or self.error is not None:
                raise ValueError("successful result requires generated_image and no error")
        elif self.error is None or self.generated_image is not None:
            raise ValueError("failed or rejected result requires error and no generated_image")
        return self


class QueueRecordV1(StrictModel):
    schema_name: Literal["QueueRecordV1"] = "QueueRecordV1"
    job: ImageJobV1
    job_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempt: int = Field(default=1, ge=1, le=3)
    submitted_at: datetime
    updated_at: datetime
    last_error: ImageErrorV1 | None = None


class WaveTaskV1(StrictModel):
    schema_name: Literal["WaveTaskV1"] = "WaveTaskV1"
    wave_id: Identifier
    request_id: Identifier
    attempt: int = Field(ge=1, le=3)
    embedding_path: str
    positive_token_count: int = Field(gt=0, le=512)
    negative_token_count: int = Field(gt=0, le=512)


def canonical_job_bytes(job: ImageJobV1) -> bytes:
    payload = job.model_dump(mode="json")
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def job_sha256(job: ImageJobV1) -> str:
    return hashlib.sha256(canonical_job_bytes(job)).hexdigest()


def prompt_sha256(job: ImageJobV1, effective_negative_prompt: str) -> str:
    payload = {
        "positive_prompt": job.prompt_spec.positive_prompt,
        "negative_prompt": effective_negative_prompt,
        "prompt_id": job.prompt_spec.prompt_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def seed_for_attempt(request_id: str, attempt: int) -> int:
    digest = hashlib.sha256(f"{request_id}:{attempt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def load_job(path: Path) -> ImageJobV1:
    return ImageJobV1.model_validate_json(path.read_text(encoding="utf-8"))
