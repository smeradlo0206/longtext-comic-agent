"""Proposal-only contracts for whole-text timeline analysis."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus, StrictBaseModel
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelation,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.reliability import ProviderFailureCategory


class TemporalRelationLLMResultV1(StrictBaseModel):
    """Internal structured LLM result that can select, but never create, evidence."""

    relation: TemporalRelation = Field(description="Event A relative to Event B.")
    confidence: float = Field(ge=0, le=1, description="Confidence in this relation judgment.")
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence ids selected from the prompt-provided set.",
    )
    reasoning_summary: str | None = Field(
        default=None,
        max_length=400,
        description="Brief evidence-grounded summary, never chain-of-thought.",
    )

    @model_validator(mode="after")
    def validate_supported_relation(self) -> "TemporalRelationLLMResultV1":
        """Keep V2 deliberately smaller than the legacy temporal enum."""

        allowed = {
            TemporalRelation.BEFORE,
            TemporalRelation.AFTER,
            TemporalRelation.SIMULTANEOUS,
            TemporalRelation.OVERLAPS,
            TemporalRelation.UNKNOWN,
        }
        if self.relation not in allowed:
            raise ValueError("TimelineAgent V2 returned an unsupported temporal relation")
        if self.relation != TemporalRelation.UNKNOWN and not self.supporting_evidence_ids:
            raise ValueError("known temporal relations require supporting_evidence_ids")
        return self


class TimelineConflictCategory(StrEnum):
    """Conflict types detected without changing source proposals."""

    MISSING_EVENT_REFERENCE = "MISSING_EVENT_REFERENCE"
    CONTRADICTORY_CLAIMS = "CONTRADICTORY_CLAIMS"


class DuplicateCandidateType(StrEnum):
    """Kinds of candidates that may refer to the same narrative fact."""

    EVENT = "EVENT"
    CLAIM = "CLAIM"


class TimelineAnalysisMode(StrEnum):
    """Execution mode for a timeline analysis request."""

    RULES_ONLY = "RULES_ONLY"
    LLM = "LLM"


class TimelinePairInferenceV1(StrictBaseModel):
    """Small Provider-facing contract for one ordered event pair.

    Internal proposal ids and EvidenceRef values are deliberately absent.  The
    Timeline Agent supplies those deterministically from the approved input.
    """

    schema_version: Literal["1.0"] = Field(default="1.0")
    relation: TemporalRelation
    evidence_indexes: list[int] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)
    reasoning_summary: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_evidence_selection(self) -> "TimelinePairInferenceV1":
        if len(self.evidence_indexes) != len(set(self.evidence_indexes)):
            raise ValueError("evidence_indexes must be unique")
        if any(index < 0 for index in self.evidence_indexes):
            raise ValueError("evidence_indexes cannot be negative")
        if self.relation == TemporalRelation.UNKNOWN and self.evidence_indexes:
            raise ValueError("UNKNOWN relation cannot select evidence")
        if self.relation != TemporalRelation.UNKNOWN and not self.evidence_indexes:
            raise ValueError("known relation requires at least one evidence index")
        return self


class ReviewGate3Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class Gate3HumanReviewResolution(StrEnum):
    """Narrow final decisions available to an explicit human reviewer."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Gate3HumanReviewInputV1(StrictBaseModel):
    """Caller-supplied fields required to resolve one held Gate 3 run."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    gate3_run_id: str = Field(min_length=1)
    resolution: Gate3HumanReviewResolution
    reviewer_id: str = Field(min_length=1)
    note: str | None = Field(default=None, min_length=1, max_length=2000)


class Gate3HumanReviewRequestV1(StrictBaseModel):
    """HTTP body for a run id already supplied by the request path."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    resolution: Gate3HumanReviewResolution
    reviewer_id: str = Field(min_length=1)
    note: str | None = Field(default=None, min_length=1, max_length=2000)


class Gate3HumanReviewV1(Gate3HumanReviewInputV1):
    """Persisted human resolution layered over the automated Gate 3 result."""

    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    automated_decision: Literal[ReviewGate3Decision.NEEDS_HUMAN_REVIEW] = (
        ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    )
    final_decision: ReviewGate3Decision

    @model_validator(mode="after")
    def validate_human_resolution(self) -> "Gate3HumanReviewV1":
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != timedelta(0):
            raise ValueError("reviewed_at must be UTC")
        expected = (
            ReviewGate3Decision.APPROVED
            if self.resolution == Gate3HumanReviewResolution.APPROVE
            else ReviewGate3Decision.REJECTED
        )
        if self.final_decision != expected:
            raise ValueError("final_decision must match the human resolution")
        return self


class Gate3HumanReviewResponseV1(StrictBaseModel):
    """Safe finalized state returned by the human-review HTTP operation."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    gate3_run_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    status: Literal[ReviewGate3Decision.APPROVED, ReviewGate3Decision.REJECTED]
    automated_decision: Literal[ReviewGate3Decision.NEEDS_HUMAN_REVIEW]
    effective_decision: Literal[ReviewGate3Decision.APPROVED, ReviewGate3Decision.REJECTED]
    human_review: Gate3HumanReviewV1
    approved_timeline_bundle_id: str | None = Field(default=None, min_length=1)
    approved_timeline_bundle_available: bool

    @model_validator(mode="after")
    def validate_finalized_response(self) -> "Gate3HumanReviewResponseV1":
        available = self.approved_timeline_bundle_id is not None
        if available != self.approved_timeline_bundle_available:
            raise ValueError("bundle availability must match approved_timeline_bundle_id")
        if self.status == ReviewGate3Decision.APPROVED and not available:
            raise ValueError("APPROVED response requires an approved Timeline bundle")
        if self.status == ReviewGate3Decision.REJECTED and available:
            raise ValueError("REJECTED response cannot contain an approved Timeline bundle")
        if self.effective_decision != self.status:
            raise ValueError("effective_decision must match status")
        return self


class TimelineGate3IssueCode(StrEnum):
    TEMPORAL_CYCLE = "TEMPORAL_CYCLE"
    UNSUPPORTED_RELATION = "UNSUPPORTED_RELATION"
    EVIDENCE_OUT_OF_SCOPE = "EVIDENCE_OUT_OF_SCOPE"
    UNKNOWN_EVENT_REFERENCE = "UNKNOWN_EVENT_REFERENCE"
    CONFLICTING_RELATIONS = "CONFLICTING_RELATIONS"
    AMBIGUOUS_ORDERING = "AMBIGUOUS_ORDERING"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    REVIEW_EXECUTION_FAILED = "REVIEW_EXECUTION_FAILED"


class TimelineGate3IssueSeverity(StrEnum):
    WARNING = "WARNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKING = "BLOCKING"


class TimelineGate3IssueV1(StrictBaseModel):
    """A structured, source-free Gate 3 diagnostic."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    issue_id: str = Field(min_length=1)
    issue_code: TimelineGate3IssueCode
    severity: TimelineGate3IssueSeverity
    related_event_ids: list[str] = Field(default_factory=list)
    related_relation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    recoverable: bool = False
    safe_recovery_action: str | None = Field(default=None, min_length=1)
    sanitized_message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_recovery_marking(self) -> "TimelineGate3IssueV1":
        if self.recoverable and self.issue_code == TimelineGate3IssueCode.AMBIGUOUS_ORDERING:
            raise ValueError("AMBIGUOUS_ORDERING cannot be automatically recoverable")
        if not self.recoverable and self.safe_recovery_action is not None:
            raise ValueError("safe_recovery_action requires recoverable=true")
        return self


class ReviewGate3ResultV1(StrictBaseModel):
    """Typed audit for exactly one Timeline candidate result."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    review_id: str = Field(min_length=1)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project_id: str = Field(min_length=1)
    source_approved_proposal_bundle_id: str = Field(min_length=1)
    timeline_run_id: str = Field(min_length=1)
    reviewer_agent_run_id: str = Field(min_length=1)
    decision: ReviewGate3Decision
    issues: list[TimelineGate3IssueV1] = Field(default_factory=list)
    safe_summary: str = Field(min_length=1)
    issue_count: int = Field(ge=0)
    checked_event_ids: list[str] = Field(default_factory=list)
    checked_temporal_relation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    human_review: Gate3HumanReviewV1 | None = None
    effective_decision: ReviewGate3Decision | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "ReviewGate3ResultV1":
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != timedelta(0):
            raise ValueError("reviewed_at must be UTC")
        if self.issue_count != len(self.issues):
            raise ValueError("issue_count must match issues")
        if self.decision == ReviewGate3Decision.APPROVED and self.issues:
            raise ValueError("APPROVED Gate 3 results cannot contain issues")
        if self.decision != ReviewGate3Decision.APPROVED and not self.issues:
            raise ValueError("non-APPROVED Gate 3 results require issues")
        if self.human_review is None:
            if self.effective_decision not in {None, self.decision}:
                raise ValueError("effective_decision requires matching human review metadata")
        else:
            if self.decision != ReviewGate3Decision.NEEDS_HUMAN_REVIEW:
                raise ValueError("human review requires an automated NEEDS_HUMAN_REVIEW decision")
            if self.human_review.gate3_run_id != self.timeline_run_id:
                raise ValueError("human review gate3_run_id must match timeline_run_id")
            if self.effective_decision != self.human_review.final_decision:
                raise ValueError("effective_decision must match the human final decision")
        return self


class NarrativeTimelineReviewRouteV1(StrictBaseModel):
    """Safe next-step routing; only APPROVED contains a Timeline bundle."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    route_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    timeline_run_id: str = Field(min_length=1)
    route: ReviewGate3Decision
    approved_timeline_bundle_id: str | None = Field(default=None, min_length=1)
    approved_timeline_bundle: "ApprovedTimelineBundleV1 | None" = None
    held_issue_ids: list[str] = Field(default_factory=list)
    safe_issue_codes: list[TimelineGate3IssueCode] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_route(self) -> "NarrativeTimelineReviewRouteV1":
        if self.route == ReviewGate3Decision.APPROVED:
            if (
                self.approved_timeline_bundle is None
                or self.approved_timeline_bundle_id is None
                or self.held_issue_ids
            ):
                raise ValueError("APPROVED route requires a bundle and no held issues")
            if self.approved_timeline_bundle.bundle_id != self.approved_timeline_bundle_id:
                raise ValueError("APPROVED route bundle id must match its bundle")
        elif (
            self.approved_timeline_bundle is not None
            or self.approved_timeline_bundle_id is not None
        ):
            raise ValueError("non-APPROVED route cannot expose a bundle")
        if self.route == ReviewGate3Decision.NEEDS_HUMAN_REVIEW and not self.held_issue_ids:
            raise ValueError("NEEDS_HUMAN_REVIEW requires held issue ids")
        if self.route != ReviewGate3Decision.NEEDS_HUMAN_REVIEW and self.held_issue_ids:
            raise ValueError("only NEEDS_HUMAN_REVIEW can hold issue ids")
        return self


class ApprovedTimelineBundleV1(StrictBaseModel):
    """Reviewed temporal material; not a StoryBible or SceneContext shortcut."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    bundle_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_approved_proposal_bundle_id: str = Field(min_length=1)
    source_gate2_review_id: str = Field(min_length=1)
    source_gate2_route_id: str = Field(min_length=1)
    timeline_run_id: str = Field(min_length=1)
    gate3_review_id: str = Field(min_length=1)
    gate3_route_id: str = Field(min_length=1)
    temporal_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_bundle(self) -> "ApprovedTimelineBundleV1":
        if len(self.event_ids) != len(set(self.event_ids)):
            raise ValueError("event_ids must be unique")
        if any(
            relation.source_event_id not in self.event_ids
            or relation.target_event_id not in self.event_ids
            for relation in self.temporal_relations
        ):
            raise ValueError("relations must reference approved event ids")
        return self


class TimelineConflictV1(StrictBaseModel):
    """Reviewable timeline conflict between proposal records."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    conflict_id: str = Field(description="Conflict id.")
    project_id: str = Field(description="Owning project id.")
    category: TimelineConflictCategory = Field(description="Conflict classification.")
    summary: str = Field(min_length=1, description="Human-readable conflict explanation.")
    affected_proposal_ids: list[str] = Field(min_length=1, description="Related proposal ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="Supporting evidence.")
    blocking: bool = Field(default=True, description="Whether review is required before promotion.")


class DuplicateCandidateV1(StrictBaseModel):
    """Possible duplicate that requires a later merge or human decision."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    candidate_id: str = Field(description="Duplicate-candidate id.")
    project_id: str = Field(description="Owning project id.")
    candidate_type: DuplicateCandidateType = Field(description="Compared proposal type.")
    proposal_ids: list[str] = Field(
        min_length=2, max_length=2, description="Compared proposal ids."
    )
    reason: str = Field(min_length=1, description="Deterministic similarity reason.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1, description="Evidence from both candidates."
    )
    confidence: float = Field(ge=0, le=1, description="Duplicate confidence.")

    @model_validator(mode="after")
    def proposal_ids_are_distinct(self) -> "DuplicateCandidateV1":
        if self.proposal_ids[0] == self.proposal_ids[1]:
            raise ValueError("duplicate candidate proposal_ids must be distinct")
        return self


class TimelineAnalysisInputV1(StrictBaseModel):
    """Whole-text candidate records supplied to the Timeline Agent."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = Field(
        default="1.1", description="Schema version."
    )
    project_id: str = Field(description="Owning project id.")
    source_approved_bundle_id: str | None = Field(
        default=None, description="Approved Gate 2 bundle id when built by the campus adapter."
    )
    source_review_run_id: str | None = Field(
        default=None, description="Gate 2 review run id when built by the campus adapter."
    )
    source_content_profile_id: str | None = Field(
        default=None, description="Approved campus profile id when built by the campus adapter."
    )
    mode: TimelineAnalysisMode = Field(
        default=TimelineAnalysisMode.RULES_ONLY,
        description="RULES_ONLY preserves V1 behavior; LLM infers selected event pairs.",
    )
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    claim_proposals: list[ClaimProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_source_candidates(self) -> "TimelineAnalysisInputV1":
        provenance_ids = (
            self.source_approved_bundle_id,
            self.source_review_run_id,
            self.source_content_profile_id,
        )
        if self.schema_version == "1.2":
            if any(not isinstance(value, str) or not value.strip() for value in provenance_ids):
                raise ValueError(
                    "schema_version=1.2 requires approved bundle, review, and profile ids"
                )
        elif self.schema_version == "1.3":
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (self.source_approved_bundle_id, self.source_review_run_id)
            ):
                raise ValueError("schema_version=1.3 requires approved bundle and review ids")
            if (
                self.source_content_profile_id is not None
                and not self.source_content_profile_id.strip()
            ):
                raise ValueError("source_content_profile_id cannot be blank")
        elif any(value is not None for value in provenance_ids):
            raise ValueError("Timeline provenance ids require schema_version=1.2")
        if not (self.event_proposals or self.claim_proposals or self.state_change_proposals):
            raise ValueError("timeline analysis requires at least one proposal")
        has_evidence = any(proposal.evidence_refs for proposal in self.event_proposals)
        has_evidence = has_evidence or any(
            proposal.evidence_refs for proposal in self.claim_proposals
        )
        has_evidence = has_evidence or any(
            proposal.evidence_refs for proposal in self.state_change_proposals
        )
        if not has_evidence:
            raise ValueError("timeline analysis requires at least one evidence reference")
        return self


class TimelineAnalysisProposalV1(StrictBaseModel):
    """Candidate timeline analysis; no output is canonical story data."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    proposal_id: str = Field(description="Timeline-analysis proposal id.")
    project_id: str = Field(description="Owning project id.")
    status: RecordStatus = Field(default=RecordStatus.CANDIDATE)
    temporal_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    conflicts: list[TimelineConflictV1] = Field(default_factory=list)
    duplicate_candidates: list[DuplicateCandidateV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="Input-derived evidence.")
    confidence: float = Field(ge=0, le=1, description="Analysis confidence.")


class TimelineGate3RunStatus(StrEnum):
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    REVIEWING = "REVIEWING"
    RECOVERY_RUNNING = "RECOVERY_RUNNING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class TimelineRecoveryBudgetV1(StrictBaseModel):
    """Persisted hard caps for one safe structural Timeline recovery sequence."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    max_attempts: int = Field(default=1, ge=0)
    max_total_tokens: int = Field(default=0, ge=0)
    max_elapsed_seconds: int = Field(default=60, ge=1)
    attempts_used: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    elapsed_seconds_used: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_usage(self) -> "TimelineRecoveryBudgetV1":
        if self.attempts_used > self.max_attempts:
            raise ValueError("recovery attempts_used exceeds max_attempts")
        if self.tokens_used > self.max_total_tokens:
            raise ValueError("recovery tokens_used exceeds max_total_tokens")
        if self.elapsed_seconds_used > self.max_elapsed_seconds:
            raise ValueError("recovery elapsed_seconds_used exceeds budget")
        return self


class TimelineProviderDiagnosticsV1(StrictBaseModel):
    """Allowlisted, source-free diagnostics for a failed Timeline Provider call."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    expected_output_schema: str | None = Field(default=None, min_length=1, max_length=128)
    schema_error_field_paths: list[str] = Field(default_factory=list, max_length=32)
    schema_error_rule_codes: list[str] = Field(default_factory=list, max_length=32)
    finish_reason: str | None = Field(default=None, min_length=1, max_length=64)


class TimelineGate3RunV1(StrictBaseModel):
    """Durable non-canonical work state for exactly one Gate 2 approved bundle."""

    schema_version: Literal["1.0", "1.1", "1.2"] = Field(default="1.2")
    timeline_run_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_approved_proposal_bundle_id: str = Field(min_length=1)
    source_gate2_review_id: str = Field(min_length=1)
    source_gate2_route_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: TimelineGate3RunStatus
    timeline_input: TimelineAnalysisInputV1 | None = None
    timeline_proposal: TimelineAnalysisProposalV1 | None = None
    timeline_agent_run_id: str | None = None
    gate3_result: ReviewGate3ResultV1 | None = None
    gate3_route: NarrativeTimelineReviewRouteV1 | None = None
    approved_timeline_bundle: ApprovedTimelineBundleV1 | None = None
    provider_request_count: int = Field(default=0, ge=0)
    failure_category: ProviderFailureCategory | None = None
    safe_issue_codes: list[str] = Field(default_factory=list)
    provider_diagnostics: TimelineProviderDiagnosticsV1 | None = None
    recovery_budget: TimelineRecoveryBudgetV1 = Field(default_factory=TimelineRecoveryBudgetV1)
    initial_timeline_proposal: TimelineAnalysisProposalV1 | None = None
    initial_gate3_result: ReviewGate3ResultV1 | None = None
    initial_gate3_route: NarrativeTimelineReviewRouteV1 | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_checkpoint(self) -> "TimelineGate3RunV1":
        after_provider = {
            TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
            TimelineGate3RunStatus.REVIEWING,
            TimelineGate3RunStatus.APPROVED,
            TimelineGate3RunStatus.REJECTED,
            TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
            TimelineGate3RunStatus.RECOVERY_RUNNING,
        }
        if self.status in after_provider and (
            self.timeline_input is None
            or self.timeline_proposal is None
            or self.timeline_agent_run_id is None
        ):
            raise ValueError("post-provider states require Timeline input/output/AgentRun")
        if self.status == TimelineGate3RunStatus.APPROVED:
            human_approved = (
                self.gate3_result is not None
                and self.gate3_result.human_review is not None
                and self.gate3_result.effective_decision == ReviewGate3Decision.APPROVED
            )
            if (self.approved_timeline_bundle is None and not human_approved) or (
                self.gate3_route is None
            ):
                raise ValueError("APPROVED state requires a Gate 3 approval")
        elif self.approved_timeline_bundle is not None:
            raise ValueError("only APPROVED state may expose a Timeline bundle")
        preserved = (
            self.initial_timeline_proposal,
            self.initial_gate3_result,
            self.initial_gate3_route,
        )
        if any(item is not None for item in preserved) and not all(
            item is not None for item in preserved
        ):
            raise ValueError("initial rejected Timeline artifacts must be retained together")
        return self


NarrativeTimelineReviewRouteV1.model_rebuild()
