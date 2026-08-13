"""Review Gate 2 proposal-review contracts.

These models record deterministic or human review outcomes.  They deliberately
do not resolve references, modify proposals, or create canonical StoryBible data.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    RelationshipSignalProposalV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1


class ProposalReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class ReviewGate2RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class ReviewMethod(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    HUMAN = "HUMAN"


class ReviewCheckStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReviewIssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKING = "BLOCKING"


class ReviewIssueCategory(StrEnum):
    INPUT = "INPUT"
    SCHEMA = "SCHEMA"
    PROVENANCE = "PROVENANCE"
    EVIDENCE = "EVIDENCE"
    REFERENCE = "REFERENCE"
    DUPLICATE = "DUPLICATE"
    MODE_BOUNDARY = "MODE_BOUNDARY"
    REALITY_LAYER = "REALITY_LAYER"
    EXECUTION = "EXECUTION"


class ReferenceResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


class ReferenceResolutionBasis(StrEnum):
    EXPLICIT_PROPOSAL_ID = "EXPLICIT_PROPOSAL_ID"
    EXACT_UNIQUE_MENTION = "EXACT_UNIQUE_MENTION"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    NONE = "NONE"


class ReviewableProposalMode(StrEnum):
    EVENT_EXTRACTION = "event_extraction"
    ENTITY_EXTRACTION = "entity_extraction"
    CLAIM_EXTRACTION = "claim_extraction"
    KNOWLEDGE_STATE_EXTRACTION = "knowledge_state_extraction"
    STATE_CHANGE_EXTRACTION = "state_change_extraction"
    RELATIONSHIP_SIGNAL_EXTRACTION = "relationship_signal_extraction"


class ReviewIssueCode(StrEnum):
    ANALYSIS_RUN_MISMATCH = "ANALYSIS_RUN_MISMATCH"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_ID_DUPLICATE = "PROPOSAL_ID_DUPLICATE"
    PROPOSAL_SCHEMA_MISMATCH = "PROPOSAL_SCHEMA_MISMATCH"
    UNSUPPORTED_PROPOSAL_SCHEMA = "UNSUPPORTED_PROPOSAL_SCHEMA"
    MODE_SCHEMA_MISMATCH = "MODE_SCHEMA_MISMATCH"
    AGENT_RUN_NOT_FOUND = "AGENT_RUN_NOT_FOUND"
    PROVENANCE_MISSING = "PROVENANCE_MISSING"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_CHUNK_NOT_FOUND = "EVIDENCE_CHUNK_NOT_FOUND"
    EVIDENCE_QUOTE_NOT_FOUND = "EVIDENCE_QUOTE_NOT_FOUND"
    EVIDENCE_RANGE_INCOMPLETE = "EVIDENCE_RANGE_INCOMPLETE"
    EVIDENCE_RANGE_OUT_OF_BOUNDS = "EVIDENCE_RANGE_OUT_OF_BOUNDS"
    EVIDENCE_OFFSET_MISMATCH = "EVIDENCE_OFFSET_MISMATCH"
    EVIDENCE_OUTSIDE_ANALYSIS_SCOPE = "EVIDENCE_OUTSIDE_ANALYSIS_SCOPE"
    REFERENCE_TARGET_NOT_FOUND = "REFERENCE_TARGET_NOT_FOUND"
    REFERENCE_TARGET_OUTSIDE_REVIEW_SCOPE = "REFERENCE_TARGET_OUTSIDE_REVIEW_SCOPE"
    REFERENCE_SCHEMA_MISMATCH = "REFERENCE_SCHEMA_MISMATCH"
    UNSUPPORTED_RESOLVED_REFERENCE = "UNSUPPORTED_RESOLVED_REFERENCE"
    AMBIGUOUS_ENTITY_REFERENCE = "AMBIGUOUS_ENTITY_REFERENCE"
    AMBIGUOUS_EVENT_REFERENCE = "AMBIGUOUS_EVENT_REFERENCE"
    REQUIRED_REFERENCE_UNRESOLVED = "REQUIRED_REFERENCE_UNRESOLVED"
    CROSS_REALITY_LAYER_REFERENCE = "CROSS_REALITY_LAYER_REFERENCE"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    POSSIBLE_SEMANTIC_DUPLICATE = "POSSIBLE_SEMANTIC_DUPLICATE"
    MODE_BOUNDARY_VIOLATION = "MODE_BOUNDARY_VIOLATION"
    CLAIM_PROMOTED_TO_FACT = "CLAIM_PROMOTED_TO_FACT"
    KNOWLEDGE_PROMOTED_TO_FACT = "KNOWLEDGE_PROMOTED_TO_FACT"
    RELATIONSHIP_SIGNAL_PROMOTED_TO_CANONICAL = "RELATIONSHIP_SIGNAL_PROMOTED_TO_CANONICAL"
    STATE_CHANGE_UNSUPPORTED_SEMANTICS = "STATE_CHANGE_UNSUPPORTED_SEMANTICS"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    REVIEW_EXECUTION_FAILED = "REVIEW_EXECUTION_FAILED"


type ProposalSchemaName = Literal[
    "EventProposalV1",
    "EntityProposalV1",
    "ClaimProposalV1",
    "KnowledgeStateProposalV1",
    "StateChangeProposalV1",
    "RelationshipSignalProposalV1",
]
type ReferenceTargetSchemaName = Literal["EntityProposalV1", "EventProposalV1", "ClaimProposalV1"]
type ReviewableProposal = (
    EventProposalV1
    | EntityProposalV1
    | ClaimProposalV1
    | KnowledgeStateProposalV1
    | StateChangeProposalV1
    | RelationshipSignalProposalV1
)

_PROPOSAL_METADATA: dict[type[StrictBaseModel], tuple[str, str]] = {
    EventProposalV1: ("EventProposalV1", ReviewableProposalMode.EVENT_EXTRACTION.value),
    EntityProposalV1: ("EntityProposalV1", ReviewableProposalMode.ENTITY_EXTRACTION.value),
    ClaimProposalV1: ("ClaimProposalV1", ReviewableProposalMode.CLAIM_EXTRACTION.value),
    KnowledgeStateProposalV1: (
        "KnowledgeStateProposalV1",
        ReviewableProposalMode.KNOWLEDGE_STATE_EXTRACTION.value,
    ),
    StateChangeProposalV1: (
        "StateChangeProposalV1",
        ReviewableProposalMode.STATE_CHANGE_EXTRACTION.value,
    ),
    RelationshipSignalProposalV1: (
        "RelationshipSignalProposalV1",
        ReviewableProposalMode.RELATIONSHIP_SIGNAL_EXTRACTION.value,
    ),
}


def _require_nonblank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _require_unique(values: Sequence[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must contain unique values")


def _has_issue(
    issues: list["ReviewIssueV1"],
    *,
    category: ReviewIssueCategory | None = None,
    severity: ReviewIssueSeverity | None = None,
) -> bool:
    return any(
        (category is None or issue.category == category)
        and (severity is None or issue.severity == severity)
        for issue in issues
    )


class ReviewIssueV1(StrictBaseModel):
    """Sanitized, auditable finding; never a provider response or source payload."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    issue_id: str
    code: ReviewIssueCode
    category: ReviewIssueCategory
    severity: ReviewIssueSeverity
    field_path: str | None = None
    evidence_index: int | None = Field(default=None, ge=0)
    related_object_ids: list[str] = Field(default_factory=list)
    sanitized_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("issue_id", "sanitized_message")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        return _require_nonblank(value, "issue_id or sanitized_message")

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str | None) -> str | None:
        if value is not None:
            _require_nonblank(value, "field_path")
        return value

    @field_validator("related_object_ids")
    @classmethod
    def validate_related_ids(cls, value: list[str]) -> list[str]:
        for object_id in value:
            _require_nonblank(object_id, "related_object_ids item")
        _require_unique(value, "related_object_ids")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("created_at must be UTC")
        return value


class EvidenceReviewItemV1(StrictBaseModel):
    """Independent review result for one EvidenceRef without repairing it."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    evidence_index: int = Field(ge=0)
    evidence_ref: EvidenceRefV1
    status: ReviewCheckStatus
    issues: list[ReviewIssueV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_result(self) -> "EvidenceReviewItemV1":
        if self.status not in {ReviewCheckStatus.PASSED, ReviewCheckStatus.FAILED}:
            raise ValueError("evidence review status must be PASSED or FAILED")
        if self.status == ReviewCheckStatus.FAILED and not _has_issue(
            self.issues,
            category=ReviewIssueCategory.EVIDENCE,
            severity=ReviewIssueSeverity.BLOCKING,
        ):
            raise ValueError("FAILED evidence review requires an EVIDENCE BLOCKING issue")
        if self.status == ReviewCheckStatus.PASSED and _has_issue(
            self.issues, severity=ReviewIssueSeverity.BLOCKING
        ):
            raise ValueError("PASSED evidence review cannot contain a BLOCKING issue")
        return self


class ReferenceTargetCandidateV1(StrictBaseModel):
    """A current-review-scope Proposal candidate, never a canonical object."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    target_proposal_id: str
    target_proposal_schema: ReferenceTargetSchemaName
    match_basis: ReferenceResolutionBasis
    source_mention: str | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> "ReferenceTargetCandidateV1":
        _require_nonblank(self.target_proposal_id, "target_proposal_id")
        if self.match_basis == ReferenceResolutionBasis.NONE:
            raise ValueError("reference candidate match_basis cannot be NONE")
        if self.source_mention is not None:
            _require_nonblank(self.source_mention, "source_mention")
        return self


class ReferenceResolutionDecisionV1(StrictBaseModel):
    """Review record for an exact, bounded Proposal reference decision."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    reference_path: str
    mention_text: str | None = None
    expected_target_schemas: list[ReferenceTargetSchemaName] = Field(min_length=1)
    required_for_downstream: bool
    status: ReferenceResolutionStatus
    candidates: list[ReferenceTargetCandidateV1] = Field(default_factory=list)
    selected_target_proposal_id: str | None = None
    selected_target_proposal_schema: ReferenceTargetSchemaName | None = None
    resolution_basis: ReferenceResolutionBasis
    issues: list[ReviewIssueV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ReferenceResolutionDecisionV1":
        _require_nonblank(self.reference_path, "reference_path")
        if self.mention_text is not None:
            _require_nonblank(self.mention_text, "mention_text")
        expected = list(self.expected_target_schemas)
        _require_unique(expected, "expected_target_schemas")
        candidate_keys = [
            (candidate.target_proposal_id, candidate.target_proposal_schema)
            for candidate in self.candidates
        ]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("candidates must have unique proposal id/schema pairs")

        selected_id = self.selected_target_proposal_id
        selected_schema = self.selected_target_proposal_schema
        if self.status == ReferenceResolutionStatus.RESOLVED:
            if not selected_id or selected_schema is None:
                raise ValueError("RESOLVED reference requires selected target id and schema")
            if selected_schema not in self.expected_target_schemas:
                raise ValueError("selected target schema must be expected")
            if self.resolution_basis == ReferenceResolutionBasis.NONE:
                raise ValueError("RESOLVED reference requires a resolution basis")
            if (selected_id, selected_schema) not in candidate_keys:
                raise ValueError("selected target must exist in candidates")
        elif self.status == ReferenceResolutionStatus.UNRESOLVED:
            if selected_id is not None or selected_schema is not None or self.candidates:
                raise ValueError(
                    "UNRESOLVED reference cannot include selected target or candidates"
                )
            if self.resolution_basis != ReferenceResolutionBasis.NONE:
                raise ValueError("UNRESOLVED reference requires resolution_basis NONE")
            if self.required_for_downstream and not _has_issue(
                self.issues, severity=ReviewIssueSeverity.REVIEW_REQUIRED
            ):
                raise ValueError("required UNRESOLVED reference requires a REVIEW_REQUIRED issue")
        elif self.status == ReferenceResolutionStatus.AMBIGUOUS:
            if selected_id is not None or selected_schema is not None:
                raise ValueError("AMBIGUOUS reference cannot select a target")
            if len(candidate_keys) < 2:
                raise ValueError("AMBIGUOUS reference requires at least two candidates")
            if self.resolution_basis != ReferenceResolutionBasis.NONE:
                raise ValueError("AMBIGUOUS reference requires resolution_basis NONE")
            if not _has_issue(self.issues, severity=ReviewIssueSeverity.REVIEW_REQUIRED):
                raise ValueError("AMBIGUOUS reference requires a REVIEW_REQUIRED issue")
        else:
            if selected_id is not None or selected_schema is not None:
                raise ValueError("REJECTED reference cannot select a target")
            if self.resolution_basis != ReferenceResolutionBasis.NONE:
                raise ValueError("REJECTED reference requires resolution_basis NONE")
            if not _has_issue(self.issues, severity=ReviewIssueSeverity.BLOCKING):
                raise ValueError("REJECTED reference requires a BLOCKING issue")
        return self


class ReviewableProposalEnvelopeV1(StrictBaseModel):
    """One unmodified Narrative Analyst Proposal with its audit provenance."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    mode: ReviewableProposalMode
    proposal_schema: ProposalSchemaName
    proposal: ReviewableProposal
    agent_run_ids: list[str] = Field(min_length=1)
    aggregated_evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_proposal_metadata(self) -> "ReviewableProposalEnvelopeV1":
        for agent_run_id in self.agent_run_ids:
            _require_nonblank(agent_run_id, "agent_run_ids item")
        _require_unique(self.agent_run_ids, "agent_run_ids")
        metadata = _PROPOSAL_METADATA.get(type(self.proposal))
        if metadata is None:
            raise ValueError("proposal must be a supported Narrative Analyst Proposal")
        expected_schema, expected_mode = metadata
        if self.proposal_schema != expected_schema:
            raise ValueError("proposal_schema does not match proposal type")
        if self.mode != expected_mode:
            raise ValueError("mode does not match proposal type")
        return self


class ReviewGate2PolicyV1(StrictBaseModel):
    """Fixed v1 safety policy snapshot; it is not a dynamic policy system."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    policy_id: str
    require_evidence: Literal[True] = True
    exact_reference_matching_only: Literal[True] = True
    allow_fuzzy_reference_matching: Literal[False] = False
    allow_llm_reference_resolution: Literal[False] = False
    allow_canonical_writes: Literal[False] = False
    require_complete_review_before_downstream: Literal[True] = True
    required_unresolved_action: Literal["NEEDS_HUMAN_REVIEW"] = "NEEDS_HUMAN_REVIEW"

    @field_validator("policy_id")
    @classmethod
    def validate_policy_id(cls, value: str) -> str:
        return _require_nonblank(value, "policy_id")


class ReviewGate2InputV1(StrictBaseModel):
    """Bounded Review Gate 2 input; it contains no canonical or provider payloads."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    project_id: str
    document_id: str
    analysis_run_id: str
    proposals: list[ReviewableProposalEnvelopeV1] = Field(default_factory=list)
    allowed_chunk_ids: list[str] = Field(default_factory=list)
    policy: ReviewGate2PolicyV1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_input_scope(self) -> "ReviewGate2InputV1":
        for field_name in ("project_id", "document_id", "analysis_run_id"):
            _require_nonblank(getattr(self, field_name), field_name)
        for chunk_id in self.allowed_chunk_ids:
            _require_nonblank(chunk_id, "allowed_chunk_ids item")
        _require_unique(self.allowed_chunk_ids, "allowed_chunk_ids")
        keys = [(item.proposal_schema, item.proposal.proposal_id) for item in self.proposals]
        if len(keys) != len(set(keys)):
            raise ValueError("proposals must have unique proposal schema/id keys")
        return self


class ProposalReviewDecisionV1(StrictBaseModel):
    """Auditable decision for one original Proposal; it never mutates that Proposal."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    decision_id: str
    analysis_run_id: str
    proposal_id: str
    proposal_schema: ProposalSchemaName
    mode: ReviewableProposalMode
    decision: ProposalReviewDecision
    schema_status: ReviewCheckStatus
    provenance_status: ReviewCheckStatus
    evidence_status: ReviewCheckStatus
    mode_boundary_status: ReviewCheckStatus
    evidence_reviews: list[EvidenceReviewItemV1] = Field(default_factory=list)
    reference_decisions: list[ReferenceResolutionDecisionV1] = Field(default_factory=list)
    issues: list[ReviewIssueV1] = Field(default_factory=list)
    review_method: ReviewMethod
    reviewed_by: str
    review_note: str | None = None
    supersedes_decision_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "ProposalReviewDecisionV1":
        for field_name in ("decision_id", "analysis_run_id", "proposal_id", "reviewed_by"):
            _require_nonblank(getattr(self, field_name), field_name)
        if self.review_note is not None:
            _require_nonblank(self.review_note, "review_note")
        if self.supersedes_decision_id is not None:
            _require_nonblank(self.supersedes_decision_id, "supersedes_decision_id")
        evidence_indexes = [review.evidence_index for review in self.evidence_reviews]
        if len(evidence_indexes) != len(set(evidence_indexes)):
            raise ValueError("evidence_reviews must have unique evidence_index values")
        reference_paths = [reference.reference_path for reference in self.reference_decisions]
        _require_unique(reference_paths, "reference_decisions reference_path")
        issue_ids = [issue.issue_id for issue in self.issues]
        _require_unique(issue_ids, "issues issue_id")
        if self.review_method == ReviewMethod.HUMAN:
            if self.supersedes_decision_id is None or self.review_note is None:
                raise ValueError("HUMAN decision requires supersedes_decision_id and review_note")
        elif self.supersedes_decision_id is not None:
            raise ValueError("DETERMINISTIC decision cannot supersede another decision")

        checks = (
            self.schema_status,
            self.provenance_status,
            self.evidence_status,
            self.mode_boundary_status,
        )
        required_unresolved = any(
            reference.required_for_downstream
            and reference.status
            in {
                ReferenceResolutionStatus.UNRESOLVED,
                ReferenceResolutionStatus.AMBIGUOUS,
                ReferenceResolutionStatus.REJECTED,
            }
            for reference in self.reference_decisions
        )
        if self.decision == ProposalReviewDecision.APPROVED:
            if any(
                status not in {ReviewCheckStatus.PASSED, ReviewCheckStatus.NOT_APPLICABLE}
                for status in checks
            ):
                raise ValueError("APPROVED decision requires passed or not-applicable checks")
            if _has_issue(self.issues, severity=ReviewIssueSeverity.BLOCKING) or _has_issue(
                self.issues, severity=ReviewIssueSeverity.REVIEW_REQUIRED
            ):
                raise ValueError(
                    "APPROVED decision cannot contain BLOCKING or REVIEW_REQUIRED issues"
                )
            if any(review.status != ReviewCheckStatus.PASSED for review in self.evidence_reviews):
                raise ValueError("APPROVED decision requires all evidence reviews to pass")
            if required_unresolved:
                raise ValueError("APPROVED decision cannot retain required unresolved references")
        elif self.decision == ProposalReviewDecision.REJECTED:
            if ReviewCheckStatus.FAILED not in checks:
                raise ValueError("REJECTED decision requires a FAILED check")
            if not _has_issue(self.issues, severity=ReviewIssueSeverity.BLOCKING):
                raise ValueError("REJECTED decision requires a BLOCKING issue")
        else:
            if _has_issue(self.issues, severity=ReviewIssueSeverity.BLOCKING):
                raise ValueError("NEEDS_HUMAN_REVIEW cannot contain a BLOCKING issue")
            pending = ReviewCheckStatus.NEEDS_HUMAN_REVIEW in checks or required_unresolved
            if not pending:
                raise ValueError("NEEDS_HUMAN_REVIEW requires a pending check or reference")
            if not _has_issue(self.issues, severity=ReviewIssueSeverity.REVIEW_REQUIRED):
                raise ValueError("NEEDS_HUMAN_REVIEW requires a REVIEW_REQUIRED issue")
        return self


class ApprovedProposalItemV1(StrictBaseModel):
    """Unmodified approved source Proposal for the future Continuity Timeline."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    source: ReviewableProposalEnvelopeV1
    review_decision_id: str
    reference_decisions: list[ReferenceResolutionDecisionV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_item(self) -> "ApprovedProposalItemV1":
        _require_nonblank(self.review_decision_id, "review_decision_id")
        paths = [reference.reference_path for reference in self.reference_decisions]
        _require_unique(paths, "reference_decisions reference_path")
        return self


class ApprovedProposalBundleV1(StrictBaseModel):
    """The only Review Gate 2 output intended for Continuity Timeline input."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    bundle_id: str
    project_id: str
    document_id: str
    analysis_run_id: str
    review_run_id: str
    policy_id: str
    approved_proposals: list[ApprovedProposalItemV1] = Field(default_factory=list)
    review_decision_ids: list[str] = Field(default_factory=list)
    unresolved_nonblocking_references: list[ReferenceResolutionDecisionV1] = Field(
        default_factory=list
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_bundle(self) -> "ApprovedProposalBundleV1":
        for field_name in (
            "bundle_id",
            "project_id",
            "document_id",
            "analysis_run_id",
            "review_run_id",
            "policy_id",
        ):
            _require_nonblank(getattr(self, field_name), field_name)
        keys = [
            (item.source.proposal_schema, item.source.proposal.proposal_id)
            for item in self.approved_proposals
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("approved_proposals must have unique proposal schema/id keys")
        _require_unique(self.review_decision_ids, "review_decision_ids")
        if set(self.review_decision_ids) != {
            item.review_decision_id for item in self.approved_proposals
        }:
            raise ValueError(
                "review_decision_ids must exactly match approved proposal decision ids"
            )
        for reference in self.unresolved_nonblocking_references:
            if (
                reference.status != ReferenceResolutionStatus.UNRESOLVED
                or reference.required_for_downstream
            ):
                raise ValueError("bundle can retain only nonblocking UNRESOLVED references")
        return self


class ReviewGate2ResultV1(StrictBaseModel):
    """Complete Review Gate 2 result, including an all-or-nothing approved bundle."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    review_run_id: str
    project_id: str
    document_id: str
    analysis_run_id: str
    status: ReviewGate2RunStatus
    policy: ReviewGate2PolicyV1
    decisions: list[ProposalReviewDecisionV1] = Field(default_factory=list)
    total_count: int = Field(ge=0)
    approved_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    needs_human_review_count: int = Field(ge=0)
    approved_bundle: ApprovedProposalBundleV1 | None = None
    execution_issues: list[ReviewIssueV1] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_result(self) -> "ReviewGate2ResultV1":
        for field_name in ("review_run_id", "project_id", "document_id", "analysis_run_id"):
            _require_nonblank(getattr(self, field_name), field_name)
        decision_ids = [decision.decision_id for decision in self.decisions]
        _require_unique(decision_ids, "decisions decision_id")
        proposal_keys = [
            (decision.proposal_schema, decision.proposal_id) for decision in self.decisions
        ]
        if len(proposal_keys) != len(set(proposal_keys)):
            raise ValueError("decisions must have unique proposal schema/id keys")
        if any(decision.analysis_run_id != self.analysis_run_id for decision in self.decisions):
            raise ValueError("every decision analysis_run_id must match the result")
        counts = {
            ProposalReviewDecision.APPROVED: sum(
                decision.decision == ProposalReviewDecision.APPROVED for decision in self.decisions
            ),
            ProposalReviewDecision.REJECTED: sum(
                decision.decision == ProposalReviewDecision.REJECTED for decision in self.decisions
            ),
            ProposalReviewDecision.NEEDS_HUMAN_REVIEW: sum(
                decision.decision == ProposalReviewDecision.NEEDS_HUMAN_REVIEW
                for decision in self.decisions
            ),
        }
        if (
            self.total_count != len(self.decisions)
            or self.approved_count != counts[ProposalReviewDecision.APPROVED]
            or self.rejected_count != counts[ProposalReviewDecision.REJECTED]
            or self.needs_human_review_count != counts[ProposalReviewDecision.NEEDS_HUMAN_REVIEW]
            or self.total_count
            != self.approved_count + self.rejected_count + self.needs_human_review_count
        ):
            raise ValueError("result counts must match decisions")
        if self.status == ReviewGate2RunStatus.COMPLETED:
            if self.needs_human_review_count:
                raise ValueError("COMPLETED result cannot contain NEEDS_HUMAN_REVIEW decisions")
            if self.approved_bundle is None:
                raise ValueError("COMPLETED result requires an approved_bundle")
        elif self.status == ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW:
            if not self.needs_human_review_count or self.approved_bundle is not None:
                raise ValueError(
                    "NEEDS_HUMAN_REVIEW result requires pending decisions and no bundle"
                )
        else:
            if self.approved_bundle is not None:
                raise ValueError("FAILED result cannot include an approved_bundle")
            if not _has_issue(
                self.execution_issues,
                category=ReviewIssueCategory.EXECUTION,
                severity=ReviewIssueSeverity.BLOCKING,
            ):
                raise ValueError("FAILED result requires an EXECUTION BLOCKING issue")

        if self.approved_bundle is not None:
            bundle = self.approved_bundle
            if (
                bundle.project_id != self.project_id
                or bundle.document_id != self.document_id
                or bundle.analysis_run_id != self.analysis_run_id
                or bundle.review_run_id != self.review_run_id
                or bundle.policy_id != self.policy.policy_id
            ):
                raise ValueError("approved_bundle ids must match the result and policy")
            decisions_by_key = {
                (decision.proposal_schema, decision.proposal_id): decision
                for decision in self.decisions
            }
            bundle_keys = []
            for item in bundle.approved_proposals:
                key = (item.source.proposal_schema, item.source.proposal.proposal_id)
                decision = decisions_by_key.get(key)
                if decision is None or decision.decision != ProposalReviewDecision.APPROVED:
                    raise ValueError("approved bundle item must correspond to an APPROVED decision")
                if item.review_decision_id != decision.decision_id:
                    raise ValueError(
                        "approved bundle item decision id must match its APPROVED decision"
                    )
                bundle_keys.append(key)
            approved_keys = {
                (decision.proposal_schema, decision.proposal_id)
                for decision in self.decisions
                if decision.decision == ProposalReviewDecision.APPROVED
            }
            if set(bundle_keys) != approved_keys:
                raise ValueError("every APPROVED decision must appear exactly once in the bundle")
        return self


class ReviewGate1RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class SourceReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class ReviewGate1IssueCategory(StrEnum):
    DOCUMENT = "DOCUMENT"
    ENCODING = "ENCODING"
    WHITESPACE = "WHITESPACE"
    CHAPTER = "CHAPTER"
    CHUNK = "CHUNK"
    ORDER = "ORDER"
    RANGE = "RANGE"
    DUPLICATE = "DUPLICATE"
    EXECUTION = "EXECUTION"


class ReviewGate1IssueCode(StrEnum):
    DOCUMENT_EMPTY = "DOCUMENT_EMPTY"
    DOCUMENT_CHECKSUM_MISMATCH = "DOCUMENT_CHECKSUM_MISMATCH"
    DOCUMENT_TEXT_REPLACEMENT_CHARACTER = "DOCUMENT_TEXT_REPLACEMENT_CHARACTER"
    DOCUMENT_FORBIDDEN_CONTROL_CHARACTER = "DOCUMENT_FORBIDDEN_CONTROL_CHARACTER"
    DOCUMENT_EXCESSIVE_WHITESPACE = "DOCUMENT_EXCESSIVE_WHITESPACE"
    CHAPTER_ID_DUPLICATE = "CHAPTER_ID_DUPLICATE"
    CHAPTER_ORDER_DUPLICATE = "CHAPTER_ORDER_DUPLICATE"
    CHAPTER_ORDER_NON_CONTIGUOUS = "CHAPTER_ORDER_NON_CONTIGUOUS"
    CHAPTER_SCOPE_MISMATCH = "CHAPTER_SCOPE_MISMATCH"
    CHAPTER_TITLE_BLANK = "CHAPTER_TITLE_BLANK"
    CHAPTER_EMPTY = "CHAPTER_EMPTY"
    CHAPTER_CHUNK_RANGE_MISMATCH = "CHAPTER_CHUNK_RANGE_MISMATCH"
    CHUNK_ID_DUPLICATE = "CHUNK_ID_DUPLICATE"
    CHUNK_ORDER_DUPLICATE = "CHUNK_ORDER_DUPLICATE"
    CHUNK_ORDER_NON_CONTIGUOUS = "CHUNK_ORDER_NON_CONTIGUOUS"
    CHUNK_SCOPE_MISMATCH = "CHUNK_SCOPE_MISMATCH"
    CHUNK_CHAPTER_NOT_FOUND = "CHUNK_CHAPTER_NOT_FOUND"
    CHUNK_TEXT_WHITESPACE_ONLY = "CHUNK_TEXT_WHITESPACE_ONLY"
    CHUNK_CHECKSUM_MISMATCH = "CHUNK_CHECKSUM_MISMATCH"
    CHUNK_OFFSETS_MISSING = "CHUNK_OFFSETS_MISSING"
    CHUNK_OFFSET_OUT_OF_BOUNDS = "CHUNK_OFFSET_OUT_OF_BOUNDS"
    CHUNK_TEXT_RANGE_MISMATCH = "CHUNK_TEXT_RANGE_MISMATCH"
    CHUNK_RANGE_OVERLAP = "CHUNK_RANGE_OVERLAP"
    CHUNK_RANGE_DUPLICATE = "CHUNK_RANGE_DUPLICATE"
    CHUNK_TEXT_EXACT_DUPLICATE = "CHUNK_TEXT_EXACT_DUPLICATE"
    CHUNK_LENGTH_EXCEEDS_POLICY = "CHUNK_LENGTH_EXCEEDS_POLICY"
    NO_USABLE_CHUNKS = "NO_USABLE_CHUNKS"
    GATE1_EXECUTION_FAILED = "GATE1_EXECUTION_FAILED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class SourceChunkUsability(StrEnum):
    USABLE = "USABLE"
    EXCLUDED = "EXCLUDED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class ReviewGate1Check(StrEnum):
    DOCUMENT_TEXT = "DOCUMENT_TEXT"
    ENCODING = "ENCODING"
    WHITESPACE = "WHITESPACE"
    CHAPTER_SCOPE = "CHAPTER_SCOPE"
    CHAPTER_ORDER = "CHAPTER_ORDER"
    CHUNK_SCOPE = "CHUNK_SCOPE"
    CHUNK_ORDER = "CHUNK_ORDER"
    CHUNK_TEXT = "CHUNK_TEXT"
    CHUNK_CHECKSUM = "CHUNK_CHECKSUM"
    CHUNK_RANGE = "CHUNK_RANGE"
    CHUNK_DUPLICATE = "CHUNK_DUPLICATE"
    CHUNK_LENGTH = "CHUNK_LENGTH"


class SourceTextAuditSnapshotV1(StrictBaseModel):
    """In-memory normalized text snapshot used only for deterministic auditing."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    normalized_text: str
    normalized_text_checksum: str
    declared_encoding: Literal["utf-8"] = "utf-8"
    decode_mode: Literal["strict"] = "strict"
    newline_normalization: Literal["CRLF_TO_LF"] = "CRLF_TO_LF"

    @field_validator("normalized_text_checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        return _require_nonblank(value, "normalized_text_checksum")


class ReviewGate1PolicyV1(StrictBaseModel):
    """Fixed source-quality safety policy; not a dynamic review configuration."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    policy_id: str
    require_utf8_strict_decode: Literal[True] = True
    require_document_checksum_match: Literal[True] = True
    require_chunk_checksum_match: Literal[True] = True
    require_char_offsets: Literal[True] = True
    require_contiguous_chunk_order: Literal[True] = True
    require_unique_chunk_ids: Literal[True] = True
    allow_overlapping_chunk_ranges: Literal[False] = False
    allow_auto_repair: Literal[False] = False
    allow_llm_review: Literal[False] = False
    allow_canonical_writes: Literal[False] = False
    allow_partial_document_downstream: Literal[False] = False
    max_expected_chunk_chars: Literal[1200] = 1200

    @field_validator("policy_id")
    @classmethod
    def validate_policy_id(cls, value: str) -> str:
        return _require_nonblank(value, "policy_id")


class ReviewGate1InputV1(StrictBaseModel):
    """Auditable source snapshot; quality anomalies remain admissible as input."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    project_id: str
    document: SourceDocumentV1
    source_text: SourceTextAuditSnapshotV1
    chapters: list[SourceChapterV1] = Field(default_factory=list)
    chunks: list[SourceChunkV1] = Field(default_factory=list)
    policy: ReviewGate1PolicyV1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_scope_identity(self) -> "ReviewGate1InputV1":
        _require_nonblank(self.project_id, "project_id")
        return self


_GATE1_CODE_RULES: dict[ReviewGate1IssueCode, tuple[ReviewGate1IssueCategory, ReviewGate1Check]] = {
    ReviewGate1IssueCode.DOCUMENT_EMPTY: (
        ReviewGate1IssueCategory.DOCUMENT,
        ReviewGate1Check.DOCUMENT_TEXT,
    ),
    ReviewGate1IssueCode.DOCUMENT_CHECKSUM_MISMATCH: (
        ReviewGate1IssueCategory.DOCUMENT,
        ReviewGate1Check.DOCUMENT_TEXT,
    ),
    ReviewGate1IssueCode.DOCUMENT_TEXT_REPLACEMENT_CHARACTER: (
        ReviewGate1IssueCategory.ENCODING,
        ReviewGate1Check.ENCODING,
    ),
    ReviewGate1IssueCode.DOCUMENT_FORBIDDEN_CONTROL_CHARACTER: (
        ReviewGate1IssueCategory.ENCODING,
        ReviewGate1Check.ENCODING,
    ),
    ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE: (
        ReviewGate1IssueCategory.WHITESPACE,
        ReviewGate1Check.WHITESPACE,
    ),
    ReviewGate1IssueCode.CHAPTER_ID_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHAPTER_ORDER,
    ),
    ReviewGate1IssueCode.CHAPTER_ORDER_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHAPTER_ORDER,
    ),
    ReviewGate1IssueCode.CHAPTER_ORDER_NON_CONTIGUOUS: (
        ReviewGate1IssueCategory.ORDER,
        ReviewGate1Check.CHAPTER_ORDER,
    ),
    ReviewGate1IssueCode.CHAPTER_SCOPE_MISMATCH: (
        ReviewGate1IssueCategory.CHAPTER,
        ReviewGate1Check.CHAPTER_SCOPE,
    ),
    ReviewGate1IssueCode.CHAPTER_TITLE_BLANK: (
        ReviewGate1IssueCategory.CHAPTER,
        ReviewGate1Check.CHAPTER_SCOPE,
    ),
    ReviewGate1IssueCode.CHAPTER_EMPTY: (
        ReviewGate1IssueCategory.CHAPTER,
        ReviewGate1Check.CHAPTER_SCOPE,
    ),
    ReviewGate1IssueCode.CHAPTER_CHUNK_RANGE_MISMATCH: (
        ReviewGate1IssueCategory.RANGE,
        ReviewGate1Check.CHAPTER_SCOPE,
    ),
    ReviewGate1IssueCode.CHUNK_ID_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHUNK_DUPLICATE,
    ),
    ReviewGate1IssueCode.CHUNK_ORDER_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHUNK_ORDER,
    ),
    ReviewGate1IssueCode.CHUNK_ORDER_NON_CONTIGUOUS: (
        ReviewGate1IssueCategory.ORDER,
        ReviewGate1Check.CHUNK_ORDER,
    ),
    ReviewGate1IssueCode.CHUNK_SCOPE_MISMATCH: (
        ReviewGate1IssueCategory.CHUNK,
        ReviewGate1Check.CHUNK_SCOPE,
    ),
    ReviewGate1IssueCode.CHUNK_CHAPTER_NOT_FOUND: (
        ReviewGate1IssueCategory.CHUNK,
        ReviewGate1Check.CHUNK_SCOPE,
    ),
    ReviewGate1IssueCode.CHUNK_TEXT_WHITESPACE_ONLY: (
        ReviewGate1IssueCategory.WHITESPACE,
        ReviewGate1Check.CHUNK_TEXT,
    ),
    ReviewGate1IssueCode.CHUNK_CHECKSUM_MISMATCH: (
        ReviewGate1IssueCategory.CHUNK,
        ReviewGate1Check.CHUNK_CHECKSUM,
    ),
    ReviewGate1IssueCode.CHUNK_OFFSETS_MISSING: (
        ReviewGate1IssueCategory.RANGE,
        ReviewGate1Check.CHUNK_RANGE,
    ),
    ReviewGate1IssueCode.CHUNK_OFFSET_OUT_OF_BOUNDS: (
        ReviewGate1IssueCategory.RANGE,
        ReviewGate1Check.CHUNK_RANGE,
    ),
    ReviewGate1IssueCode.CHUNK_TEXT_RANGE_MISMATCH: (
        ReviewGate1IssueCategory.RANGE,
        ReviewGate1Check.CHUNK_RANGE,
    ),
    ReviewGate1IssueCode.CHUNK_RANGE_OVERLAP: (
        ReviewGate1IssueCategory.RANGE,
        ReviewGate1Check.CHUNK_RANGE,
    ),
    ReviewGate1IssueCode.CHUNK_RANGE_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHUNK_DUPLICATE,
    ),
    ReviewGate1IssueCode.CHUNK_TEXT_EXACT_DUPLICATE: (
        ReviewGate1IssueCategory.DUPLICATE,
        ReviewGate1Check.CHUNK_DUPLICATE,
    ),
    ReviewGate1IssueCode.CHUNK_LENGTH_EXCEEDS_POLICY: (
        ReviewGate1IssueCategory.CHUNK,
        ReviewGate1Check.CHUNK_LENGTH,
    ),
    ReviewGate1IssueCode.NO_USABLE_CHUNKS: (
        ReviewGate1IssueCategory.CHUNK,
        ReviewGate1Check.CHUNK_TEXT,
    ),
    ReviewGate1IssueCode.GATE1_EXECUTION_FAILED: (
        ReviewGate1IssueCategory.EXECUTION,
        ReviewGate1Check.CHUNK_TEXT,
    ),
    ReviewGate1IssueCode.HUMAN_REVIEW_REQUIRED: (
        ReviewGate1IssueCategory.EXECUTION,
        ReviewGate1Check.CHUNK_TEXT,
    ),
}


class ReviewGate1IssueV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    issue_id: str
    code: ReviewGate1IssueCode
    category: ReviewGate1IssueCategory
    severity: ReviewIssueSeverity
    check: ReviewGate1Check
    related_document_id: str | None = None
    related_chapter_input_indexes: list[int] = Field(default_factory=list)
    related_chunk_input_indexes: list[int] = Field(default_factory=list)
    field_path: str | None = None
    sanitized_message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_issue(self) -> "ReviewGate1IssueV1":
        _require_nonblank(self.issue_id, "issue_id")
        _require_nonblank(self.sanitized_message, "sanitized_message")
        if "\n" in self.sanitized_message or "\r" in self.sanitized_message:
            raise ValueError("sanitized_message must not contain newlines")
        if self.field_path is not None:
            _require_nonblank(self.field_path, "field_path")
        for field_name in ("related_chapter_input_indexes", "related_chunk_input_indexes"):
            values = getattr(self, field_name)
            if any(value < 0 for value in values):
                raise ValueError(f"{field_name} must contain non-negative indexes")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique indexes")
        expected = _GATE1_CODE_RULES[self.code]
        if (self.category, self.check) != expected:
            raise ValueError("issue code category/check mismatch")
        return self


class ReviewGate1CheckResultV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    check: ReviewGate1Check
    status: ReviewCheckStatus
    issue_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_check_result(self) -> "ReviewGate1CheckResultV1":
        _require_unique(self.issue_ids, "issue_ids")
        for issue_id in self.issue_ids:
            _require_nonblank(issue_id, "issue_ids item")
        if self.status in {ReviewCheckStatus.FAILED, ReviewCheckStatus.NEEDS_HUMAN_REVIEW}:
            if not self.issue_ids:
                raise ValueError("non-passed check requires issue_ids")
        return self


class SourceChapterReviewItemV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    chapter_input_index: int = Field(ge=0)
    chapter_id: str
    chapter_order: int = Field(ge=0)
    status: ReviewCheckStatus
    check_results: list[ReviewGate1CheckResultV1] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_chapter_item(self) -> "SourceChapterReviewItemV1":
        _require_nonblank(self.chapter_id, "chapter_id")
        _require_unique(self.issue_ids, "issue_ids")
        return self


class SourceChunkReviewItemV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    chunk_input_index: int = Field(ge=0)
    chunk_id: str
    chunk_order: int = Field(ge=0)
    chapter_id: str
    usability: SourceChunkUsability
    status: ReviewCheckStatus
    check_results: list[ReviewGate1CheckResultV1] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_chunk_item(self) -> "SourceChunkReviewItemV1":
        _require_nonblank(self.chunk_id, "chunk_id")
        _require_nonblank(self.chapter_id, "chapter_id")
        _require_unique(self.issue_ids, "issue_ids")
        if (
            self.usability == SourceChunkUsability.USABLE
            and self.status != ReviewCheckStatus.PASSED
        ):
            raise ValueError("USABLE chunk must have PASSED status")
        if (
            self.usability == SourceChunkUsability.EXCLUDED
            and self.status != ReviewCheckStatus.FAILED
        ):
            raise ValueError("EXCLUDED chunk must have FAILED status")
        if (
            self.usability == SourceChunkUsability.NEEDS_HUMAN_REVIEW
            and self.status != ReviewCheckStatus.NEEDS_HUMAN_REVIEW
        ):
            raise ValueError("NEEDS_HUMAN_REVIEW chunk must have pending status")
        return self


class ApprovedSourceChunkBundleV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    project_id: str
    document_id: str
    document_checksum: str
    review_run_id: str
    policy_id: str
    chunk_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> "ApprovedSourceChunkBundleV1":
        for field_name in (
            "project_id",
            "document_id",
            "document_checksum",
            "review_run_id",
            "policy_id",
        ):
            _require_nonblank(getattr(self, field_name), field_name)
        for chunk_id in self.chunk_ids:
            _require_nonblank(chunk_id, "chunk_ids item")
        _require_unique(self.chunk_ids, "chunk_ids")
        return self


class ReviewGate1ResultV1(StrictBaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")
    review_run_id: str
    project_id: str
    document_id: str
    document_checksum: str
    policy: ReviewGate1PolicyV1
    status: ReviewGate1RunStatus
    decision: SourceReviewDecision
    document_checks: list[ReviewGate1CheckResultV1] = Field(default_factory=list)
    chapter_reviews: list[SourceChapterReviewItemV1] = Field(default_factory=list)
    chunk_reviews: list[SourceChunkReviewItemV1] = Field(default_factory=list)
    issues: list[ReviewGate1IssueV1] = Field(default_factory=list)
    approved_chunk_bundle: ApprovedSourceChunkBundleV1 | None = None
    review_method: Literal[ReviewMethod.DETERMINISTIC] = ReviewMethod.DETERMINISTIC
    reviewed_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_result(self) -> "ReviewGate1ResultV1":
        for field_name in (
            "review_run_id",
            "project_id",
            "document_id",
            "document_checksum",
            "reviewed_by",
        ):
            _require_nonblank(getattr(self, field_name), field_name)
        issue_map = {issue.issue_id: issue for issue in self.issues}
        if len(issue_map) != len(self.issues):
            raise ValueError("issues issue_id must be unique")
        chapter_indexes = [item.chapter_input_index for item in self.chapter_reviews]
        chunk_indexes = [item.chunk_input_index for item in self.chunk_reviews]
        if chapter_indexes != list(range(len(chapter_indexes))):
            raise ValueError("chapter review input indexes must be contiguous from zero")
        if chunk_indexes != list(range(len(chunk_indexes))):
            raise ValueError("chunk review input indexes must be contiguous from zero")
        chapter_orders = [item.chapter_order for item in self.chapter_reviews]
        chunk_orders = [item.chunk_order for item in self.chunk_reviews]
        if chapter_orders != list(range(len(chapter_orders))):
            raise ValueError("chapter review orders must be contiguous from zero")
        if chunk_orders != list(range(len(chunk_orders))):
            raise ValueError("chunk review orders must be contiguous from zero")
        if len({item.chapter_id for item in self.chapter_reviews}) != len(self.chapter_reviews):
            raise ValueError("chapter review ids must be unique")
        if len({item.chunk_id for item in self.chunk_reviews}) != len(self.chunk_reviews):
            raise ValueError("chunk review ids must be unique")
        self._validate_review_references(issue_map)
        blocking = any(issue.severity == ReviewIssueSeverity.BLOCKING for issue in self.issues)
        review_required = any(
            issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED for issue in self.issues
        )
        if self.status == ReviewGate1RunStatus.COMPLETED:
            if self.decision == SourceReviewDecision.APPROVED:
                if blocking or review_required or self.approved_chunk_bundle is None:
                    raise ValueError(
                        "APPROVED result requires no blocking/review issue and a bundle"
                    )
                if any(
                    item.usability != SourceChunkUsability.USABLE for item in self.chunk_reviews
                ):
                    raise ValueError("APPROVED result requires all chunks to be USABLE")
            elif self.decision == SourceReviewDecision.REJECTED:
                if not blocking or self.approved_chunk_bundle is not None:
                    raise ValueError("REJECTED result requires a blocking issue and no bundle")
                if self.chunk_reviews and not any(
                    item.usability == SourceChunkUsability.EXCLUDED for item in self.chunk_reviews
                ):
                    raise ValueError("REJECTED result requires an excluded chunk")
            else:
                raise ValueError("COMPLETED result decision must be APPROVED or REJECTED")
        elif self.status == ReviewGate1RunStatus.NEEDS_HUMAN_REVIEW:
            if self.decision != SourceReviewDecision.NEEDS_HUMAN_REVIEW:
                raise ValueError("pending result requires NEEDS_HUMAN_REVIEW decision")
            if not review_required or self.approved_chunk_bundle is not None:
                raise ValueError("pending result requires review-required issue and no bundle")
            if any(
                issue.code == ReviewGate1IssueCode.GATE1_EXECUTION_FAILED
                and issue.severity == ReviewIssueSeverity.BLOCKING
                for issue in self.issues
            ):
                raise ValueError("pending result cannot contain execution failure")
        else:
            if self.decision != SourceReviewDecision.REJECTED:
                raise ValueError("FAILED result requires REJECTED decision")
            if self.approved_chunk_bundle is not None or not any(
                issue.code == ReviewGate1IssueCode.GATE1_EXECUTION_FAILED
                and issue.category == ReviewGate1IssueCategory.EXECUTION
                and issue.severity == ReviewIssueSeverity.BLOCKING
                for issue in self.issues
            ):
                raise ValueError("FAILED result requires execution blocking issue and no bundle")
        if self.approved_chunk_bundle is not None:
            bundle = self.approved_chunk_bundle
            if (
                bundle.project_id != self.project_id
                or bundle.document_id != self.document_id
                or bundle.document_checksum != self.document_checksum
                or bundle.review_run_id != self.review_run_id
                or bundle.policy_id != self.policy.policy_id
            ):
                raise ValueError("approved chunk bundle identity must match result")
            expected_ids = [item.chunk_id for item in self.chunk_reviews]
            if bundle.chunk_ids != expected_ids:
                raise ValueError("approved chunk bundle must preserve source chunk order")
        return self

    def _validate_review_references(self, issue_map: dict[str, "ReviewGate1IssueV1"]) -> None:
        chapter_count = len(self.chapter_reviews)
        chunk_count = len(self.chunk_reviews)
        for issue in self.issues:
            if any(index >= chapter_count for index in issue.related_chapter_input_indexes):
                raise ValueError("issue references unknown chapter input index")
            if any(index >= chunk_count for index in issue.related_chunk_input_indexes):
                raise ValueError("issue references unknown chunk input index")
        all_ids: list[str] = []
        for chapter_item in self.chapter_reviews:
            all_ids.extend(chapter_item.issue_ids)
            for check in chapter_item.check_results:
                all_ids.extend(check.issue_ids)
        for chunk_item in self.chunk_reviews:
            all_ids.extend(chunk_item.issue_ids)
            for check in chunk_item.check_results:
                all_ids.extend(check.issue_ids)
        for check in self.document_checks:
            all_ids.extend(check.issue_ids)
        for issue_id in all_ids:
            if issue_id not in issue_map:
                raise ValueError("review item references unknown issue id")
        for check in self.document_checks:
            self._validate_check_severity(check, issue_map)
        for chapter_item in self.chapter_reviews:
            for check in chapter_item.check_results:
                self._validate_check_severity(check, issue_map)
        for chunk_item in self.chunk_reviews:
            for check in chunk_item.check_results:
                self._validate_check_severity(check, issue_map)

    @staticmethod
    def _validate_check_severity(
        check: ReviewGate1CheckResultV1,
        issue_map: dict[str, "ReviewGate1IssueV1"],
    ) -> None:
        severities = {issue_map[issue_id].severity for issue_id in check.issue_ids}
        if check.status == ReviewCheckStatus.FAILED:
            if ReviewIssueSeverity.BLOCKING not in severities:
                raise ValueError("FAILED check requires a BLOCKING issue")
        elif check.status == ReviewCheckStatus.NEEDS_HUMAN_REVIEW:
            if ReviewIssueSeverity.REVIEW_REQUIRED not in severities:
                raise ValueError("NEEDS_HUMAN_REVIEW check requires a REVIEW_REQUIRED issue")
        elif check.status == ReviewCheckStatus.PASSED:
            if severities & {ReviewIssueSeverity.BLOCKING, ReviewIssueSeverity.REVIEW_REQUIRED}:
                raise ValueError("PASSED check cannot reference blocking review issues")
        elif ReviewIssueSeverity.BLOCKING in severities:
            raise ValueError("NOT_APPLICABLE check cannot reference a BLOCKING issue")
