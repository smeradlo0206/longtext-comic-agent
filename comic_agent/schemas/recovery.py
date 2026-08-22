"""Typed, bounded contracts for original-mode Narrative Analyst recovery."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import StrictBaseModel
from comic_agent.schemas.review import (
    NarrativeAnalysisReviewRouteV1,
    ProposalSchemaName,
    ReviewableProposalMode,
    ReviewGate2ResultV1,
    ReviewIssueCode,
)


def _require_nonblank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _require_unique(values: list[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique values")


class RecoveryAttemptStatus(StrEnum):
    """Durable execution states for one idempotent recovery attempt."""

    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"


class RecoveryOutcomeStatus(StrEnum):
    """Safe resume states for a root-run recovery decision."""

    NOT_STARTED = "NOT_STARTED"
    SKIPPED = "SKIPPED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NON_RECOVERABLE = "NON_RECOVERABLE"
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class RecoveryTargetKind(StrEnum):
    """Bounded execution target; future modules share the same recovery vocabulary."""

    NARRATIVE_PROPOSAL = "NARRATIVE_PROPOSAL"
    NARRATIVE_WINDOW = "NARRATIVE_WINDOW"
    TIMELINE_RUN = "TIMELINE_RUN"
    STORYBIBLE_CANDIDATE = "STORYBIBLE_CANDIDATE"
    STORYBOARD_RUN = "STORYBOARD_RUN"


class RecoveryStrategy(StrEnum):
    """Fixed strategies only; recovery never contains free-form instructions."""

    RETRY_SAME_SCOPE = "RETRY_SAME_SCOPE"
    SPLIT_WINDOW = "SPLIT_WINDOW"
    RESUME_REVIEW = "RESUME_REVIEW"
    DEFER_UNTIL_RETRY = "DEFER_UNTIL_RETRY"
    STOP = "STOP"


class RecoveryBudgetUsageV1(StrictBaseModel):
    """Persisted recovery consumption, kept independent from Provider content."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_attempts: int = Field(default=0, ge=0)
    window_attempts: int = Field(default=0, ge=0)
    root_run_attempts: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    elapsed_seconds: int = Field(default=0, ge=0)
    provider_requests: int = Field(default=0, ge=0)


class RecoveryPolicyV1(StrictBaseModel):
    """Fixed allow-list and budgets; no unknown issue is recoverable by default."""

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str
    allowed_issue_codes: list[ReviewIssueCode] = Field(min_length=1)
    terminal_issue_codes: list[ReviewIssueCode] = Field(min_length=1)
    max_attempts_per_proposal: int = Field(ge=0)
    max_attempts_per_window: int = Field(ge=0)
    max_attempts_per_root_run: int = Field(ge=0)
    max_total_tokens: int = Field(ge=0)
    max_elapsed_seconds: int = Field(ge=0)
    max_provider_requests: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_classification(self) -> "RecoveryPolicyV1":
        _require_nonblank(self.policy_id, "policy_id")
        allowed = [str(code) for code in self.allowed_issue_codes]
        terminal = [str(code) for code in self.terminal_issue_codes]
        _require_unique(allowed, "allowed_issue_codes")
        _require_unique(terminal, "terminal_issue_codes")
        if set(allowed) & set(terminal):
            raise ValueError("allowed_issue_codes and terminal_issue_codes must be disjoint")
        return self


class RecoveryDirectiveV1(StrictBaseModel):
    """Deterministic original-window rerun instruction without source text or prompts."""

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    directive_id: str
    idempotency_key: str
    target_kind: RecoveryTargetKind = RecoveryTargetKind.NARRATIVE_PROPOSAL
    target_id: str | None = None
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY_SAME_SCOPE
    parent_attempt_id: str | None = None
    split_depth: int = Field(default=0, ge=0, le=8)
    max_split_depth: int = Field(default=0, ge=0, le=8)
    retry_not_before: datetime | None = None
    root_analysis_run_id: str
    project_id: str
    document_id: str
    proposal_id: str
    proposal_schema: ProposalSchemaName
    mode: ReviewableProposalMode
    original_window_id: str
    original_agent_run_id: str
    ordered_source_chunk_ids: list[str] = Field(min_length=1)
    approved_source_chunk_ids: list[str] = Field(min_length=1)
    issue_ids: list[str] = Field(min_length=1)
    issue_codes: list[ReviewIssueCode] = Field(min_length=1)
    policy: RecoveryPolicyV1
    budget_usage: RecoveryBudgetUsageV1
    max_chars_per_chunk: int = Field(default=1200, ge=1)
    max_provider_calls: int = Field(
        default=1,
        ge=1,
        le=2,
        description=(
            "Reserved calls for this locked recovery scope: one evidence repair and, "
            "only when budget permits, one schema-format repair."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_locked_scope(self) -> "RecoveryDirectiveV1":
        for field_name in (
            "directive_id",
            "idempotency_key",
            "root_analysis_run_id",
            "project_id",
            "document_id",
            "proposal_id",
            "original_window_id",
            "original_agent_run_id",
        ):
            _require_nonblank(getattr(self, field_name), field_name)
        if self.target_id is not None:
            _require_nonblank(self.target_id, "target_id")
        if self.parent_attempt_id is not None:
            _require_nonblank(self.parent_attempt_id, "parent_attempt_id")
        if self.split_depth > self.max_split_depth:
            raise ValueError("split_depth must not exceed max_split_depth")
        if self.target_kind == RecoveryTargetKind.NARRATIVE_PROPOSAL and self.target_id not in {
            None,
            self.proposal_id,
        }:
            raise ValueError("Narrative proposal target_id must match proposal_id")
        for field_name in (
            "ordered_source_chunk_ids",
            "approved_source_chunk_ids",
            "issue_ids",
        ):
            values = getattr(self, field_name)
            for value in values:
                _require_nonblank(value, f"{field_name} item")
            _require_unique(values, field_name)
        codes = [str(code) for code in self.issue_codes]
        _require_unique(codes, "issue_codes")
        if self.ordered_source_chunk_ids != self.approved_source_chunk_ids:
            raise ValueError("approved_source_chunk_ids must preserve the original ordered scope")
        if not set(codes).issubset({str(code) for code in self.policy.allowed_issue_codes}):
            raise ValueError("issue_codes must all be allowed by the recovery policy")
        return self


class RecoveryOutcomeV1(StrictBaseModel):
    """Source-free summary usable by resume, API, and Console."""

    schema_version: Literal["1.0"] = "1.0"
    outcome_id: str
    root_analysis_run_id: str
    proposal_id: str | None = None
    attempt_id: str | None = None
    status: RecoveryOutcomeStatus
    safe_issue_codes: list[ReviewIssueCode] = Field(default_factory=list)
    route_decision: str | None = None
    budget_usage: RecoveryBudgetUsageV1 = Field(default_factory=RecoveryBudgetUsageV1)
    sanitized_diagnostic: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("outcome_id", "root_analysis_run_id")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        return _require_nonblank(value, "outcome identifier")

    @field_validator("proposal_id", "attempt_id", "route_decision", "sanitized_diagnostic")
    @classmethod
    def validate_optional_nonblank(cls, value: str | None) -> str | None:
        if value is not None:
            _require_nonblank(value, "optional outcome value")
        return value


class RecoveryAttemptV1(StrictBaseModel):
    """Append-only audit record for one reserved original-mode recovery rerun."""

    schema_version: Literal["1.0"] = "1.0"
    attempt_id: str
    idempotency_key: str
    directive: RecoveryDirectiveV1
    status: RecoveryAttemptStatus
    original_gate2_issue_codes: list[ReviewIssueCode] = Field(min_length=1)
    new_agent_run_id: str | None = None
    new_proposal_ids: list[str] = Field(default_factory=list)
    budget_usage: RecoveryBudgetUsageV1 = Field(default_factory=RecoveryBudgetUsageV1)
    fresh_review_result: ReviewGate2ResultV1 | None = None
    fresh_route: NarrativeAnalysisReviewRouteV1 | None = None
    outcome: RecoveryOutcomeV1 | None = None
    sanitized_diagnostic: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_attempt_state(self) -> "RecoveryAttemptV1":
        for field_name in ("attempt_id", "idempotency_key"):
            _require_nonblank(getattr(self, field_name), field_name)
        if self.idempotency_key != self.directive.idempotency_key:
            raise ValueError("attempt idempotency_key must match directive")
        issue_codes = [str(code) for code in self.original_gate2_issue_codes]
        _require_unique(issue_codes, "original_gate2_issue_codes")
        _require_unique(self.new_proposal_ids, "new_proposal_ids")
        if (self.fresh_review_result is None) != (self.fresh_route is None):
            raise ValueError("fresh Gate 2 result and route must be present together")
        if self.status == RecoveryAttemptStatus.COMPLETED:
            if self.outcome is None or self.completed_at is None:
                raise ValueError("completed recovery attempts require outcome and completed_at")
        elif self.outcome is not None or self.completed_at is not None:
            raise ValueError("nonterminal recovery attempts cannot contain final outcome")
        if self.status == RecoveryAttemptStatus.PROVIDER_SUCCEEDED and (
            self.new_agent_run_id is None or not self.new_proposal_ids
        ):
            raise ValueError("provider-succeeded recovery attempts require new AgentRun provenance")
        if self.fresh_review_result is not None and self.fresh_route is not None:
            if self.fresh_review_result.review_run_id != self.fresh_route.review_run_id:
                raise ValueError("fresh Gate 2 route must match its result")
        return self
