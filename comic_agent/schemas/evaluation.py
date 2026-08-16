"""Offline, deterministic Knowledge State evaluation contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import StrictBaseModel
from comic_agent.schemas.narrative import (
    EpistemicBasis,
    EpistemicStatus,
    KnowledgeReferenceResolutionStatus,
    KnowledgeStateProposalBatchV1,
    KnowledgeTargetKind,
)
from comic_agent.schemas.source import SourceChunkV1


class KnowledgeStateEvaluationCategory(StrEnum):
    KNOWS = "KNOWS"
    HEARD = "HEARD"
    SUSPECTS = "SUSPECTS"
    BELIEVES = "BELIEVES"
    DISBELIEVES = "DISBELIEVES"
    UNAWARE = "UNAWARE"
    SPEECH_ONLY_NEGATIVE = "SPEECH_ONLY_NEGATIVE"
    PRESENCE_ONLY_NEGATIVE = "PRESENCE_ONLY_NEGATIVE"
    OBSERVATION_BOUNDARY = "OBSERVATION_BOUNDARY"
    TARGET_KIND_BOUNDARY = "TARGET_KIND_BOUNDARY"
    EMPTY_BATCH = "EMPTY_BATCH"


class KnowledgeStateEvaluationRiskTag(StrEnum):
    NO_KNOWS_FROM_SPEECH = "NO_KNOWS_FROM_SPEECH"
    NO_KNOWS_FROM_PRESENCE = "NO_KNOWS_FROM_PRESENCE"
    NO_KNOWS_FROM_SEEING_OBJECT = "NO_KNOWS_FROM_SEEING_OBJECT"
    NO_BELIEF_FROM_DIRECT_ASSERTION = "NO_BELIEF_FROM_DIRECT_ASSERTION"
    TARGET_KIND_BOUNDARY = "TARGET_KIND_BOUNDARY"
    RUMOR_CONTENT_NORMALIZATION = "RUMOR_CONTENT_NORMALIZATION"
    EVIDENCE_EXACTNESS = "EVIDENCE_EXACTNESS"
    UNRESOLVED_REFERENCE_BOUNDARY = "UNRESOLVED_REFERENCE_BOUNDARY"
    TEMPORAL_NULL_WHEN_ABSENT = "TEMPORAL_NULL_WHEN_ABSENT"
    EMPTY_BATCH = "EMPTY_BATCH"


class KnowledgeStateFixtureOrigin(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    REDACTED_REAL_SAMPLE = "REDACTED_REAL_SAMPLE"


class KnowledgeTemporalAnchorExpectationKind(StrEnum):
    MUST_BE_NULL = "MUST_BE_NULL"
    MUST_MATCH_UNRESOLVED_TEXT = "MUST_MATCH_UNRESOLVED_TEXT"
    MUST_MATCH_RESOLVED_EVENT = "MUST_MATCH_RESOLVED_EVENT"
    IGNORE = "IGNORE"


class KnowledgeStateTextMatchPolicy(StrEnum):
    STRICT_NORMALIZED = "STRICT_NORMALIZED"


class KnowledgeStateEvaluationFailureType(StrEnum):
    MISSING_EXPECTED_STATE = "MISSING_EXPECTED_STATE"
    FORBIDDEN_STATE_EMITTED = "FORBIDDEN_STATE_EMITTED"
    UNEXPECTED_EXTRA_STATE = "UNEXPECTED_EXTRA_STATE"
    WRONG_EPISTEMIC_STATUS = "WRONG_EPISTEMIC_STATUS"
    WRONG_EPISTEMIC_BASIS = "WRONG_EPISTEMIC_BASIS"
    WRONG_TARGET_KIND = "WRONG_TARGET_KIND"
    WRONG_TARGET_TEXT = "WRONG_TARGET_TEXT"
    EVIDENCE_QUOTE_MISMATCH = "EVIDENCE_QUOTE_MISMATCH"
    TEMPORAL_ANCHOR_SHOULD_BE_NULL = "TEMPORAL_ANCHOR_SHOULD_BE_NULL"
    UNEXPECTED_RESOLVED_REFERENCE = "UNEXPECTED_RESOLVED_REFERENCE"
    STATE_COUNT_MISMATCH = "STATE_COUNT_MISMATCH"


class KnowledgeStateEvaluationRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class KnowledgeStateEvaluationRunFailureCategory(StrEnum):
    PROVIDER_SCHEMA_VALIDATION = "PROVIDER_SCHEMA_VALIDATION"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_NETWORK = "PROVIDER_NETWORK"
    PROVIDER_HTTP = "PROVIDER_HTTP"
    PROVIDER_CONFIGURATION = "PROVIDER_CONFIGURATION"
    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"


class KnowledgeStateEvaluationFailureDiagnosticsV1(StrictBaseModel):
    """Allowlisted provider diagnostics; never raw response or prompt content."""

    schema_error_kind: str | None = None
    schema_error_field_paths: list[str] = Field(default_factory=list)
    schema_error_rule_codes: list[str] = Field(default_factory=list)
    expected_output_schema: str | None = None
    timeout_kind: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=0)
    request_attempts: int | None = Field(default=None, ge=1)
    http_status_code: int | None = Field(default=None, ge=100, le=599)


class KnowledgeStateEvaluationRunFailureV1(StrictBaseModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    case_id: str = Field(min_length=1)
    status: Literal["FAILED"] = "FAILED"
    failure_category: KnowledgeStateEvaluationRunFailureCategory
    message: str = Field(min_length=1, max_length=500)
    diagnostics: KnowledgeStateEvaluationFailureDiagnosticsV1 = Field(
        default_factory=KnowledgeStateEvaluationFailureDiagnosticsV1
    )


class KnowledgeTemporalAnchorExpectationV1(StrictBaseModel):
    expectation: KnowledgeTemporalAnchorExpectationKind = Field(
        default=KnowledgeTemporalAnchorExpectationKind.MUST_BE_NULL
    )
    anchor_text: str | None = None
    event_proposal_id: str | None = None

    @model_validator(mode="after")
    def validate_expectation_detail(self) -> "KnowledgeTemporalAnchorExpectationV1":
        if self.expectation == KnowledgeTemporalAnchorExpectationKind.MUST_MATCH_UNRESOLVED_TEXT:
            if not self.anchor_text or self.event_proposal_id is not None:
                raise ValueError("MUST_MATCH_UNRESOLVED_TEXT requires anchor_text only")
        if self.expectation == KnowledgeTemporalAnchorExpectationKind.MUST_MATCH_RESOLVED_EVENT:
            if not self.event_proposal_id or self.anchor_text is not None:
                raise ValueError("MUST_MATCH_RESOLVED_EVENT requires event_proposal_id only")
        if self.expectation in {
            KnowledgeTemporalAnchorExpectationKind.MUST_BE_NULL,
            KnowledgeTemporalAnchorExpectationKind.IGNORE,
        } and (self.anchor_text is not None or self.event_proposal_id is not None):
            raise ValueError("null or ignored temporal expectation cannot include anchor detail")
        return self


class KnowledgeStateExpectationV1(StrictBaseModel):
    subject_text: str = Field(min_length=1)
    subject_resolution_status: KnowledgeReferenceResolutionStatus
    epistemic_status: EpistemicStatus
    epistemic_basis: EpistemicBasis
    target_kind: KnowledgeTargetKind
    target_text: str = Field(min_length=1)
    target_resolution_status: KnowledgeReferenceResolutionStatus
    evidence_quote: str = Field(min_length=1)
    allowed_evidence_quotes: list[str] = Field(
        default_factory=list,
        description=(
            "Additional finite, exact source quotes that are accepted for this "
            "expectation. Text is never normalized, shortened, or fuzzily matched."
        ),
    )
    valid_from_expectation: KnowledgeTemporalAnchorExpectationV1 = Field(
        default_factory=KnowledgeTemporalAnchorExpectationV1
    )
    valid_until_expectation: KnowledgeTemporalAnchorExpectationV1 = Field(
        default_factory=KnowledgeTemporalAnchorExpectationV1
    )

    @model_validator(mode="after")
    def validate_allowed_evidence_quotes(self) -> "KnowledgeStateExpectationV1":
        all_quotes = [self.evidence_quote, *self.allowed_evidence_quotes]
        if any(not quote.strip() for quote in all_quotes):
            raise ValueError("evidence quotes must not be blank")
        if len(set(all_quotes)) != len(all_quotes):
            raise ValueError("allowed evidence quotes must be distinct")
        return self


class KnowledgeStateStateMatcherV1(StrictBaseModel):
    subject_text: str | None = None
    subject_resolution_status: KnowledgeReferenceResolutionStatus | None = None
    epistemic_status: EpistemicStatus | None = None
    epistemic_basis: EpistemicBasis | None = None
    target_kind: KnowledgeTargetKind | None = None
    target_text: str | None = None
    target_resolution_status: KnowledgeReferenceResolutionStatus | None = None
    valid_from_is_null: bool | None = None
    valid_until_is_null: bool | None = None

    @model_validator(mode="after")
    def validate_has_condition(self) -> "KnowledgeStateStateMatcherV1":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("forbidden state matcher requires at least one condition")
        return self


class KnowledgeStateEvaluationPolicyV1(StrictBaseModel):
    allow_extra_states: bool = False
    require_exact_state_count: bool = True
    require_exact_evidence_quote: bool = True
    require_null_temporal_anchors_when_absent: bool = True
    text_match_policy: KnowledgeStateTextMatchPolicy = (
        KnowledgeStateTextMatchPolicy.STRICT_NORMALIZED
    )
    expected_unresolved_references: bool = True


class KnowledgeStateEvaluationCaseV1(StrictBaseModel):
    schema_version: Literal["1.0", "1.1"] = "1.1"
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: KnowledgeStateEvaluationCategory
    risk_tags: list[KnowledgeStateEvaluationRiskTag] = Field(default_factory=list)
    fixture_origin: KnowledgeStateFixtureOrigin
    source_chunks: list[SourceChunkV1] = Field(min_length=1, max_length=3)
    expected_states: list[KnowledgeStateExpectationV1] = Field(default_factory=list)
    forbidden_states: list[KnowledgeStateStateMatcherV1] = Field(default_factory=list)
    policy: KnowledgeStateEvaluationPolicyV1 = Field(
        default_factory=KnowledgeStateEvaluationPolicyV1
    )
    notes: str | None = None

    @model_validator(mode="after")
    def validate_versioned_evidence_alternatives(self) -> "KnowledgeStateEvaluationCaseV1":
        if self.schema_version == "1.0" and any(
            state.allowed_evidence_quotes for state in self.expected_states
        ):
            raise ValueError("schema_version 1.0 does not support allowed evidence quotes")
        return self


class KnowledgeStateEvaluationCaseSummaryV1(StrictBaseModel):
    """Safe case-list payload that omits fixture source text and expectations."""

    case_id: str
    title: str
    category: KnowledgeStateEvaluationCategory
    risk_tags: list[KnowledgeStateEvaluationRiskTag] = Field(default_factory=list)
    fixture_origin: KnowledgeStateFixtureOrigin
    zero_output_expected: bool


class KnowledgeStateExpectationResultV1(StrictBaseModel):
    expected_index: int = Field(ge=0)
    matched_actual_index: int | None = Field(default=None, ge=0)
    passed: bool
    failure_types: list[KnowledgeStateEvaluationFailureType] = Field(default_factory=list)


class KnowledgeStateEvaluationFailureV1(StrictBaseModel):
    failure_type: KnowledgeStateEvaluationFailureType
    expected_index: int | None = Field(default=None, ge=0)
    actual_index: int | None = Field(default=None, ge=0)
    detail: str


class KnowledgeStateEvaluationResultV1(StrictBaseModel):
    case_id: str
    passed: bool
    expected_state_count: int
    actual_state_count: int
    matched_expected_count: int
    missing_expected: list[int] = Field(default_factory=list)
    forbidden_matches: list[int] = Field(default_factory=list)
    unexpected_actual_states: list[int] = Field(default_factory=list)
    evidence_pass_count: int
    evidence_total_count: int
    evidence_pass_rate: float = Field(ge=0, le=1)
    failure_types: list[KnowledgeStateEvaluationFailureType] = Field(default_factory=list)
    expectation_results: list[KnowledgeStateExpectationResultV1] = Field(default_factory=list)
    failures: list[KnowledgeStateEvaluationFailureV1] = Field(default_factory=list)


class KnowledgeStateEvaluationCaseBatchV1(StrictBaseModel):
    """One already-structured Batch associated with one bundled evaluation case."""

    case_id: str = Field(min_length=1)
    batch: KnowledgeStateProposalBatchV1


class KnowledgeStateEvaluationReportRequestV1(StrictBaseModel):
    """Offline batch-report input; it contains no Provider configuration or raw response."""

    evaluations: list[KnowledgeStateEvaluationCaseBatchV1] = Field(min_length=1)
    run_failures: list[KnowledgeStateEvaluationRunFailureV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "KnowledgeStateEvaluationReportRequestV1":
        case_ids = [item.case_id for item in self.evaluations]
        failure_case_ids = [item.case_id for item in self.run_failures]
        if len(set(case_ids + failure_case_ids)) != len(case_ids) + len(failure_case_ids):
            raise ValueError("evaluations must contain unique case_id values")
        return self


class KnowledgeStateEvaluationCategorySummaryV1(StrictBaseModel):
    """Deterministic pass/fail summary for one evaluation fixture category."""

    category: KnowledgeStateEvaluationCategory
    evaluated_case_count: int = Field(ge=0)
    passed_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)


class KnowledgeStateEvaluationReportV1(StrictBaseModel):
    """Transient aggregate for multiple deterministic Knowledge State evaluations."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    attempted_case_count: int = Field(default=0, ge=0)
    evaluated_case_count: int = Field(ge=0)
    passed_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    overall_pass_rate: float = Field(ge=0, le=1)
    expected_state_count: int = Field(ge=0)
    actual_state_count: int = Field(ge=0)
    matched_expected_count: int = Field(ge=0)
    status_correct_count: int = Field(ge=0)
    target_kind_correct_count: int = Field(ge=0)
    evidence_pass_count: int = Field(ge=0)
    evidence_total_count: int = Field(ge=0)
    evidence_pass_rate: float = Field(ge=0, le=1)
    run_failed_case_count: int = Field(default=0, ge=0)
    is_complete: bool = False
    acceptance_eligible: bool = False
    run_failure_category_counts: dict[KnowledgeStateEvaluationRunFailureCategory, int] = Field(
        default_factory=dict
    )
    run_failures: list[KnowledgeStateEvaluationRunFailureV1] = Field(default_factory=list)
    zero_output_case_count: int = Field(ge=0)
    zero_output_passed_count: int = Field(ge=0)
    forbidden_match_count: int = Field(ge=0)
    unexpected_resolved_reference_count: int = Field(ge=0)
    failure_type_counts: dict[KnowledgeStateEvaluationFailureType, int] = Field(
        default_factory=dict
    )
    category_summaries: list[KnowledgeStateEvaluationCategorySummaryV1] = Field(
        default_factory=list
    )
    case_results: list[KnowledgeStateEvaluationResultV1] = Field(default_factory=list)


class KnowledgeStateEvaluationEvaluateRequestV1(StrictBaseModel):
    batch: KnowledgeStateProposalBatchV1


class KnowledgeStateEvaluationRunRequestV1(StrictBaseModel):
    real_llm_requested: bool = False


class KnowledgeStateEvaluationRunResultV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(default="")
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    request_attempts: int = Field(default=1, ge=1)
    batch: KnowledgeStateProposalBatchV1
    evaluation: KnowledgeStateEvaluationResultV1


KnowledgeStateEvaluationRunOutcomeV1 = Annotated[
    KnowledgeStateEvaluationRunResultV1 | KnowledgeStateEvaluationRunFailureV1,
    Field(discriminator="status"),
]
