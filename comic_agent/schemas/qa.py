"""Quality assurance and repair planning schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus, StrictBaseModel


class PanelTextQAIssueCode(StrEnum):
    """Source-grounded semantic checks available before image generation."""

    UNSUPPORTED_PANEL_FACT = "UNSUPPORTED_PANEL_FACT"
    EVENT_MISMATCH = "EVENT_MISMATCH"
    CHARACTER_MISMATCH = "CHARACTER_MISMATCH"
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    DIALOGUE_MISMATCH = "DIALOGUE_MISMATCH"
    CONTINUITY_RISK = "CONTINUITY_RISK"


class PanelTextQAIssueSeverity(StrEnum):
    """Whether a text QA issue blocks image generation."""

    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class PanelTextQAInferenceFindingV1(StrictBaseModel):
    """Small Provider-facing finding that selects only supplied indexes."""

    schema_version: Literal["1.0"] = "1.0"
    panel_index: int = Field(ge=0)
    issue_code: PanelTextQAIssueCode
    severity: PanelTextQAIssueSeverity
    evidence_indexes: list[int] = Field(default_factory=list, max_length=8)
    summary: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def indexes_are_unique(self) -> "PanelTextQAInferenceFindingV1":
        if len(self.evidence_indexes) != len(set(self.evidence_indexes)):
            raise ValueError("evidence_indexes must be unique")
        return self


class PanelTextQAInferenceV1(StrictBaseModel):
    """Provider-facing semantic QA response without trusted object identifiers."""

    schema_version: Literal["1.0"] = "1.0"
    findings: list[PanelTextQAInferenceFindingV1] = Field(default_factory=list, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)


class PanelTextQAFindingV1(StrictBaseModel):
    """Evidence-traceable semantic issue attached to one planned panel."""

    schema_version: Literal["1.0"] = "1.0"
    finding_id: str = Field(min_length=1)
    panel_id: str = Field(min_length=1)
    issue_code: PanelTextQAIssueCode
    severity: PanelTextQAIssueSeverity
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=300)


class PanelTextQAProposalV1(StrictBaseModel):
    """Proposal-only source-vs-panel QA result; never canonical story data."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    status: RecordStatus = RecordStatus.CANDIDATE
    checked_panel_ids: list[str] = Field(min_length=1)
    findings: list[PanelTextQAFindingV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    passed: bool
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_result(self) -> "PanelTextQAProposalV1":
        if len(self.checked_panel_ids) != len(set(self.checked_panel_ids)):
            raise ValueError("checked_panel_ids must be unique")
        checked = set(self.checked_panel_ids)
        if any(item.panel_id not in checked for item in self.findings):
            raise ValueError("findings must reference checked panels")
        expected = not any(
            item.severity == PanelTextQAIssueSeverity.BLOCKING for item in self.findings
        )
        if self.passed != expected:
            raise ValueError("passed must match blocking findings")
        return self


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
