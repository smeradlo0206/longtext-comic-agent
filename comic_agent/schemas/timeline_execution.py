"""Non-canonical Timeline execution artifacts.

This contract records what the Timeline execution was able to produce without
turning an execution failure into a Timeline fact.  It is deliberately
source-free with respect to provider responses, prompts, and source text.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel
from comic_agent.schemas.narrative import TemporalRelationProposalV1
from comic_agent.schemas.reliability import ProviderFailureCategory


class TimelineExecutionStatus(StrEnum):
    """Terminal or reviewable outcome of a Timeline execution attempt."""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    NEEDS_HUMAN_ACTION = "NEEDS_HUMAN_ACTION"
    FAILED = "FAILED"


class TimelineInputAvailability(StrEnum):
    """Classify whether audited Narrative material can enter Timeline execution."""

    AVAILABLE = "AVAILABLE"
    NO_TIMELINE_CONTENT = "NO_TIMELINE_CONTENT"
    INPUT_INCOMPLETE = "INPUT_INCOMPLETE"
    INPUT_EXCLUDED = "INPUT_EXCLUDED"


class TimelineInputAvailabilitySummaryV1(StrictBaseModel):
    """Source-free counts explaining a non-provider Timeline input outcome."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    entity_proposal_count: int = Field(default=0, ge=0)
    event_proposal_count: int = Field(default=0, ge=0)
    claim_proposal_count: int = Field(default=0, ge=0)
    state_change_proposal_count: int = Field(default=0, ge=0)
    excluded_timeline_candidate_count: int = Field(default=0, ge=0)
    incomplete_modes: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("incomplete_modes")
    @classmethod
    def incomplete_modes_are_known_and_unique(cls, value: list[str]) -> list[str]:
        allowed = {"event_extraction", "claim_extraction", "state_change_extraction"}
        if any(mode not in allowed for mode in value):
            raise ValueError("incomplete_modes must contain Timeline-relevant Narrative modes")
        if len(value) != len(set(value)):
            raise ValueError("incomplete_modes must be unique")
        return value


class TimelineExecutionInputReferenceV1(StrictBaseModel):
    """Stable, source-free identity of material supplied to Timeline."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    source_approved_proposal_bundle_id: str | None = Field(default=None, min_length=1)
    source_narrative_execution_bundle_id: str | None = Field(default=None, min_length=1)
    source_gate2_review_id: str = Field(min_length=1)
    source_gate2_route_id: str = Field(min_length=1)
    event_proposal_ids: list[str] = Field(default_factory=list)
    claim_proposal_ids: list[str] = Field(default_factory=list)
    state_change_proposal_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validates_source_and_unique_ids(self) -> "TimelineExecutionInputReferenceV1":
        if (
            self.source_approved_proposal_bundle_id is None
            and self.source_narrative_execution_bundle_id is None
        ):
            raise ValueError("Timeline execution input requires source bundle provenance")
        for values, name in (
            (self.event_proposal_ids, "event_proposal_ids"),
            (self.claim_proposal_ids, "claim_proposal_ids"),
            (self.state_change_proposal_ids, "state_change_proposal_ids"),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{name} cannot contain blank ids")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        return self


class TimelineExecutionFailedItemV1(StrictBaseModel):
    """A failed Timeline unit with only allowlisted diagnostics."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    pair_id: str = Field(min_length=1, max_length=256)
    failure_category: ProviderFailureCategory
    field_path: str | None = Field(default=None, min_length=1, max_length=256)
    failure_origin: str | None = Field(default=None, min_length=1, max_length=128)
    safe_issue_codes: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("safe_issue_codes")
    @classmethod
    def safe_issue_codes_are_allowlisted(cls, value: list[str]) -> list[str]:
        if any(not code or not code.replace("_", "").isalnum() for code in value):
            raise ValueError("safe_issue_codes must be identifier-like")
        if len(value) != len(set(value)):
            raise ValueError("safe_issue_codes must be unique")
        return value


class TimelineExecutionIssueV1(StrictBaseModel):
    """An execution finding that remains reviewable without provider content."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    issue_id: str = Field(min_length=1, max_length=256)
    issue_code: str = Field(min_length=1, max_length=128)
    severity: str = Field(default="ERROR", pattern=r"^(INFO|WARNING|ERROR)$")
    failed_pair_id: str | None = Field(default=None, min_length=1, max_length=256)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)


class TimelineExecutionDiagnosticV1(StrictBaseModel):
    """One typed, source-free Timeline validation diagnostic."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    failure_origin: str | None = Field(default=None, min_length=1, max_length=128)
    field_path: str | None = Field(default=None, min_length=1, max_length=256)
    error_type: str | None = Field(default=None, min_length=1, max_length=128)
    message_type: str | None = Field(default=None, min_length=1, max_length=128)


class TimelineExecutionProvenanceV1(StrictBaseModel):
    """Execution lineage needed to review a Timeline result later."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    source_chunk_ids: list[str] = Field(default_factory=list)
    timeline_agent_run_id: str = Field(min_length=1)
    gate3_reviewer_agent_run_id: str | None = Field(default=None, min_length=1)

    @field_validator("source_chunk_ids")
    @classmethod
    def source_chunk_ids_are_unique(cls, value: list[str]) -> list[str]:
        if any(not chunk_id.strip() for chunk_id in value):
            raise ValueError("source_chunk_ids cannot contain blank ids")
        if len(value) != len(set(value)):
            raise ValueError("source_chunk_ids must be unique")
        return value


class TimelineExecutionBundleV1(StrictBaseModel):
    """Reviewable non-canonical Timeline output, including failed execution units."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.0")
    bundle_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    timeline_run_id: str = Field(min_length=1)
    status: TimelineExecutionStatus
    input_reference: TimelineExecutionInputReferenceV1
    input_availability: TimelineInputAvailability = TimelineInputAvailability.AVAILABLE
    input_availability_summary: TimelineInputAvailabilitySummaryV1 = Field(
        default_factory=TimelineInputAvailabilitySummaryV1
    )
    candidate_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    failed_items: list[TimelineExecutionFailedItemV1] = Field(default_factory=list)
    issues: list[TimelineExecutionIssueV1] = Field(default_factory=list)
    diagnostics: list[TimelineExecutionDiagnosticV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    provenance: TimelineExecutionProvenanceV1
    provider_request_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validates_execution_artifact(self) -> "TimelineExecutionBundleV1":
        pair_ids = [item.pair_id for item in self.failed_items]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("failed_items pair_id values must be unique")
        issue_ids = [item.issue_id for item in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("issues issue_id values must be unique")
        known_failed_pairs = set(pair_ids)
        if any(
            issue.failed_pair_id is not None and issue.failed_pair_id not in known_failed_pairs
            for issue in self.issues
        ):
            raise ValueError("issues must reference a failed item when failed_pair_id is set")
        # Event-reference validity remains a Gate 3 responsibility.  Keeping a
        # structurally valid but bad relation here is important: otherwise this
        # execution artifact would hide precisely the invalid candidate that
        # Gate 3 must flag for review.
        required_evidence = [
            evidence for relation in self.candidate_relations for evidence in relation.evidence_refs
        ] + [evidence for issue in self.issues for evidence in issue.evidence_refs]
        if any(evidence not in self.evidence_refs for evidence in required_evidence):
            raise ValueError("evidence_refs must cover candidate relations and issues")
        if self.status == TimelineExecutionStatus.SUCCEEDED and self.failed_items:
            raise ValueError("SUCCEEDED Timeline execution cannot retain failed items")
        if (
            self.input_availability != TimelineInputAvailability.AVAILABLE
            and self.status == TimelineExecutionStatus.SUCCEEDED
        ):
            raise ValueError("unavailable Timeline input cannot be marked SUCCEEDED")
        if self.input_availability != TimelineInputAvailability.AVAILABLE:
            if self.candidate_relations:
                raise ValueError("unavailable Timeline input cannot contain inferred relations")
            if self.provider_request_count != 0:
                raise ValueError("unavailable Timeline input cannot consume a provider request")
        if self.schema_version == "1.0" and (
            self.input_availability != TimelineInputAvailability.AVAILABLE
            or self.input_availability_summary != TimelineInputAvailabilitySummaryV1()
            or self.provider_request_count != 0
        ):
            raise ValueError(
                "schema_version=1.0 cannot contain Timeline input availability metadata"
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be UTC")
        return self
