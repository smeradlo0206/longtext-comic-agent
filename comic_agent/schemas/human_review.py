"""Contracts for the single, non-canonical human decision over a production dossier."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import StrictBaseModel


class HumanReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class HumanReviewResultStatus(StrEnum):
    READY_FOR_STORYBIBLE = "READY_FOR_STORYBIBLE"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    NEEDS_REVISION = "NEEDS_REVISION"


class HumanReviewLineageV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    source_dossier_id: str
    narrative_execution_bundle_id: str
    timeline_review_material_id: str

    @field_validator(
        "source_dossier_id", "narrative_execution_bundle_id", "timeline_review_material_id"
    )
    @classmethod
    def ids_are_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("human review lineage id cannot be blank")
        return value


class HumanReviewSubmissionV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    dossier_id: str
    decision: HumanReviewDecision
    reviewer_id: str
    reviewer_note: str | None = None

    @field_validator("project_id", "dossier_id", "reviewer_id", "reviewer_note")
    @classmethod
    def text_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("human review text cannot be blank")
        return value


class HumanReviewRunV1(StrictBaseModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    review_id: str
    project_id: str
    dossier_id: str
    dossier_hash: str
    decision: HumanReviewDecision
    reviewer_id: str
    reviewer_note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    lineage: HumanReviewLineageV1

    @model_validator(mode="after")
    def validate_lineage(self) -> "HumanReviewRunV1":
        if self.dossier_id != self.lineage.source_dossier_id:
            raise ValueError("review dossier_id must match lineage source_dossier_id")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("created_at must be UTC")
        if not self.dossier_hash.strip():
            raise ValueError("review dossier_hash cannot be blank")
        return self


class HumanReviewResultV1(StrictBaseModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    review_run: HumanReviewRunV1
    status: HumanReviewResultStatus

    @model_validator(mode="after")
    def decision_maps_to_status(self) -> "HumanReviewResultV1":
        expected = {
            HumanReviewDecision.APPROVE: HumanReviewResultStatus.READY_FOR_STORYBIBLE,
            HumanReviewDecision.REJECT: HumanReviewResultStatus.REJECTED_BY_HUMAN,
            HumanReviewDecision.REQUEST_CHANGES: HumanReviewResultStatus.NEEDS_REVISION,
        }[self.review_run.decision]
        if self.status != expected:
            raise ValueError("human review result status must match decision")
        return self
