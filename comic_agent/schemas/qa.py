"""Quality assurance and repair planning schemas."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class QAResultV1(StrictBaseModel):
    """Result of a quality gate over a target object."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    qa_result_id: str = Field(description="QA result id.")
    target_type: str = Field(description="Target type.")
    target_id: str = Field(description="Target id.")
    check_scores: dict[str, float] = Field(default_factory=dict, description="Named check scores.")
    hard_failures: list[str] = Field(default_factory=list, description="Blocking failures.")
    issues: list[dict[str, Any]] = Field(default_factory=list, description="Detailed issues.")
    passed: bool = Field(description="Whether all required checks passed.")
    evaluated_by: str = Field(description="QA agent or service id.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp in UTC.",
    )


class RepairPlanV1(StrictBaseModel):
    """Bounded repair instruction for a failed target."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    repair_plan_id: str = Field(description="Repair plan id.")
    target_id: str = Field(description="Target object id.")
    repair_type: str = Field(description="Repair type.")
    target_region: dict[str, Any] | None = Field(
        default=None,
        description="Optional target region.",
    )
    instruction: str = Field(description="Human/auditable repair instruction.")
    max_attempts: int = Field(default=1, ge=1, description="Maximum repair attempts.")
