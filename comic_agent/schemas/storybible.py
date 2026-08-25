"""Versioned, evidence-backed contracts for StoryBible curation."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus, StrictBaseModel
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.review import (
    NarrativeExecutionExcludedItemV1,
    NarrativeExecutionFailedWindowV1,
    NarrativeExecutionStatus,
    ReviewableProposalEnvelopeV1,
    ReviewIssueV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisProposalV1,
    TimelineGate3IssueV1,
)


class StoryEntityKind(StrEnum):
    """Entity kinds that are eligible for canonical StoryBible profiles."""

    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"


StoryBibleId = Annotated[str, StringConstraints(max_length=128)]
StoryBibleName = Annotated[str, StringConstraints(max_length=255)]


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class StoryEntityProfileV1(StrictBaseModel):
    """Canonical identity record for a person, organization, or location."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: StoryBibleId
    project_id: StoryBibleId
    entity_kind: StoryEntityKind
    canonical_name: StoryBibleName
    aliases: list[StoryBibleName] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("profile_id", "project_id", "canonical_name")
    @classmethod
    def identifiers_and_name_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("aliases")
    @classmethod
    def aliases_are_not_blank(cls, value: list[str]) -> list[str]:
        return [_reject_blank(alias) for alias in value]


class StoryEntityStateV1(StrictBaseModel):
    """Evidence-backed state that applies to a profile over a story-time interval."""

    schema_version: Literal["1.0"] = "1.0"
    state_id: StoryBibleId
    project_id: StoryBibleId
    profile_id: StoryBibleId
    state: dict[str, Any] = Field(default_factory=dict)
    triggering_event_id: StoryBibleId | None = None
    valid_from_event_id: StoryBibleId | None = None
    valid_until_event_id: StoryBibleId | None = None
    valid_from_order: int | None = Field(default=None, ge=0)
    valid_until_order: int | None = Field(default=None, ge=0)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("state_id", "project_id", "profile_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def temporal_interval_is_valid(self) -> "StoryEntityStateV1":
        if (
            self.valid_from_order is not None
            and self.valid_until_order is not None
            and self.valid_until_order < self.valid_from_order
        ):
            raise ValueError("valid_until_order must not precede valid_from_order")
        return self


class StoryRelationshipV1(StrictBaseModel):
    """Typed, time-bound relationship between two StoryBible profiles."""

    schema_version: Literal["1.0"] = "1.0"
    relationship_id: StoryBibleId
    project_id: StoryBibleId
    source_profile_id: StoryBibleId
    target_profile_id: StoryBibleId
    relationship_type: StoryBibleName
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid_from_event_id: StoryBibleId | None = None
    valid_until_event_id: StoryBibleId | None = None
    valid_from_order: int | None = Field(default=None, ge=0)
    valid_until_order: int | None = Field(default=None, ge=0)
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator(
        "relationship_id",
        "project_id",
        "source_profile_id",
        "target_profile_id",
        "relationship_type",
    )
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def relationship_interval_is_valid(self) -> "StoryRelationshipV1":
        if self.source_profile_id == self.target_profile_id:
            raise ValueError("relationship endpoints cannot be the same")
        if (
            self.valid_from_order is not None
            and self.valid_until_order is not None
            and self.valid_until_order < self.valid_from_order
        ):
            raise ValueError("valid_until_order must not precede valid_from_order")
        return self


class WorldRuleV1(StrictBaseModel):
    """Source-supported rule governing the story world."""

    schema_version: Literal["1.0"] = "1.0"
    rule_id: StoryBibleId
    project_id: StoryBibleId
    name: StoryBibleName
    statement: str
    scope: str | None = None
    revision: int = Field(default=1, ge=1)
    status: RecordStatus = RecordStatus.CANONICAL
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("rule_id", "project_id", "name", "statement")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class ProfileUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of an entity profile, emitted by the curator."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    profile: StoryEntityProfileV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class StateUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a time-bound entity state."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    state: StoryEntityStateV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class RelationshipUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a typed relationship."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    relationship: StoryRelationshipV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


class WorldRuleUpdateProposalV1(StrictBaseModel):
    """Candidate upsert of a world rule."""

    schema_version: Literal["1.0"] = "1.0"
    update_id: StoryBibleId
    project_id: StoryBibleId
    world_rule: WorldRuleV1
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)


StoryBibleUpdateV1 = Annotated[
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1,
    Field(discriminator=None),
]


class ConflictV1(StrictBaseModel):
    """Reviewable evidence, identity, or temporal conflict in a curation candidate."""

    schema_version: Literal["1.0"] = "1.0"
    conflict_id: StoryBibleId
    project_id: StoryBibleId
    category: str
    summary: str
    affected_update_ids: list[StoryBibleId] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    blocking: bool = True

    @field_validator("conflict_id", "project_id", "category", "summary")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class CommitPlanV1(StrictBaseModel):
    """Reviewed list of StoryBible updates eligible for CommitService processing."""

    schema_version: Literal["1.0"] = "1.0"
    commit_plan_id: StoryBibleId
    project_id: StoryBibleId
    source_proposal_id: StoryBibleId
    content_hash: StoryBibleId
    updates: list[StoryBibleUpdateV1] = Field(min_length=1)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)

    @field_validator("commit_plan_id", "project_id", "source_proposal_id", "content_hash")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleCuratorContextLineageV1(StrictBaseModel):
    """Server-owned lineage metadata exposed to the proposal-only Curator."""

    schema_version: Literal["1.0"] = "1.0"
    production_run_id: StoryBibleId
    dossier_id: StoryBibleId
    human_review_id: StoryBibleId
    approved_timeline_bundle_id: StoryBibleId | None
    canonical_snapshot_identity: StoryBibleId
    canonical_snapshot_hash: StoryBibleId

    @field_validator(
        "production_run_id",
        "dossier_id",
        "human_review_id",
        "canonical_snapshot_identity",
        "canonical_snapshot_hash",
    )
    @classmethod
    def lineage_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("approved_timeline_bundle_id")
    @classmethod
    def optional_timeline_reference_is_not_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value) if value is not None else None


class StoryBibleContextV1(StrictBaseModel):
    """Bounded context supplied to the proposal-only StoryBible curator."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    project_id: StoryBibleId
    lineage: StoryBibleCuratorContextLineageV1 | None = None
    entity_proposals: list[EntityProposalV1] = Field(default_factory=list)
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)
    temporal_relation_proposals: list[TemporalRelationProposalV1] = Field(default_factory=list)
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list, max_length=3)

    @field_validator("project_id")
    @classmethod
    def project_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class ProductionDossierProvenanceV1(StrictBaseModel):
    """Lineage references for a non-canonical StoryBible production dossier."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    narrative_analysis_run_id: StoryBibleId
    gate1_review_id: StoryBibleId
    gate2_review_run_id: StoryBibleId | None = None
    gate3_review_id: StoryBibleId | None = None
    timeline_run_id: StoryBibleId | None = None
    timeline_agent_run_id: StoryBibleId | None = None
    gate3_reviewer_agent_run_id: StoryBibleId | None = None
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list)

    @field_validator(
        "narrative_analysis_run_id",
        "gate1_review_id",
        "gate2_review_run_id",
        "gate3_review_id",
        "timeline_run_id",
        "timeline_agent_run_id",
        "gate3_reviewer_agent_run_id",
    )
    @classmethod
    def provenance_references_are_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            return _reject_blank(value)
        return value

    @field_validator("source_chunk_ids")
    @classmethod
    def source_chunk_ids_are_unique(cls, value: list[str]) -> list[str]:
        if any(not chunk_id.strip() for chunk_id in value):
            raise ValueError("source_chunk_ids cannot contain blank ids")
        if len(value) != len(set(value)):
            raise ValueError("source_chunk_ids must be unique")
        return value


class ProductionDossierIssueStage(StrEnum):
    GATE2 = "GATE2"
    EXECUTION = "EXECUTION"
    GATE3 = "GATE3"


class ProductionDossierIssueProvenanceV1(StrictBaseModel):
    """Source-bounded lineage for one unified, non-canonical review finding."""

    schema_version: Literal["1.0"] = "1.0"
    narrative_execution_bundle_id: StoryBibleId
    timeline_review_material_id: StoryBibleId | None = None
    narrative_analysis_run_id: StoryBibleId
    timeline_run_id: StoryBibleId | None = None
    related_object_ids: list[StoryBibleId] = Field(default_factory=list)

    @field_validator(
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
        "narrative_analysis_run_id",
        "timeline_run_id",
    )
    @classmethod
    def issue_provenance_ids_are_not_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value) if value is not None else value


class ProductionDossierIssueV1(StrictBaseModel):
    """One source-preserving finding for the future unified human review."""

    schema_version: Literal["1.0"] = "1.0"
    issue_id: StoryBibleId
    source_stage: ProductionDossierIssueStage
    severity: str
    source_issue_id: StoryBibleId | None = None
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    provenance: ProductionDossierIssueProvenanceV1

    @field_validator("issue_id", "severity", "source_issue_id")
    @classmethod
    def issue_text_is_not_blank(cls, value: str | None) -> str | None:
        return _reject_blank(value) if value is not None else value


class ProductionDossierNarrativeSummaryV1(StrictBaseModel):
    """Durable, non-canonical Narrative material reviewed by a human."""

    schema_version: Literal["1.0", "1.1"] = "1.1"
    execution_status: NarrativeExecutionStatus
    candidates: list[ReviewableProposalEnvelopeV1] = Field(default_factory=list)
    failed_windows: list[NarrativeExecutionFailedWindowV1] = Field(default_factory=list)
    excluded_items: list[NarrativeExecutionExcludedItemV1] = Field(default_factory=list)
    issues: list[ReviewIssueV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)


class ProductionDossierTimelineSummaryV1(StrictBaseModel):
    schema_version: Literal["1.0"] = "1.0"
    timeline_candidate: TimelineAnalysisProposalV1
    temporal_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    review_status: ReviewGate3Decision
    issues: list[TimelineGate3IssueV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)


class ProductionDossierV1(StrictBaseModel):
    """Non-canonical, evidence-backed material for the future single human review.

    It carries references to execution material and its Gate 2/Gate 3 findings.  It
    neither authorizes a StoryBible commit nor changes existing approved-bundle
    semantics.
    """

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.2"
    dossier_id: StoryBibleId
    project_id: StoryBibleId
    document_id: StoryBibleId
    narrative_execution_bundle_id: StoryBibleId
    timeline_review_material_id: StoryBibleId
    gate2_findings: list[ReviewIssueV1] = Field(default_factory=list)
    gate3_findings: list[TimelineGate3IssueV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    narrative_summary: ProductionDossierNarrativeSummaryV1 | None = None
    timeline_summary: ProductionDossierTimelineSummaryV1 | None = None
    unified_issues: list[ProductionDossierIssueV1] = Field(default_factory=list)
    provenance: ProductionDossierProvenanceV1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "dossier_id",
        "project_id",
        "document_id",
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
    )
    @classmethod
    def dossier_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_dossier_findings(self) -> "ProductionDossierV1":
        gate2_issue_ids = [issue.issue_id for issue in self.gate2_findings]
        gate3_issue_ids = [issue.issue_id for issue in self.gate3_findings]
        if len(gate2_issue_ids) != len(set(gate2_issue_ids)):
            raise ValueError("gate2_findings must have unique issue_id values")
        if len(gate3_issue_ids) != len(set(gate3_issue_ids)):
            raise ValueError("gate3_findings must have unique issue_id values")
        required_evidence = [
            evidence_ref for issue in self.gate3_findings for evidence_ref in issue.evidence_refs
        ]
        if any(evidence_ref not in self.evidence_refs for evidence_ref in required_evidence):
            raise ValueError("evidence_refs must cover Gate 3 finding evidence")
        if self.schema_version in {"1.1", "1.2"}:
            if self.narrative_summary is None or self.timeline_summary is None:
                raise ValueError("1.1 dossier requires Narrative and Timeline summaries")
            if self.narrative_summary.execution_status == NarrativeExecutionStatus.SUCCEEDED and (
                self.narrative_summary.failed_windows
            ):
                raise ValueError("SUCCEEDED Narrative summary cannot retain failed windows")
            unified_ids = [issue.issue_id for issue in self.unified_issues]
            if len(unified_ids) != len(set(unified_ids)):
                raise ValueError("unified_issues must have unique issue ids")
            summary_evidence = [
                *self.narrative_summary.evidence_refs,
                *self.timeline_summary.evidence_refs,
                *(ref for issue in self.unified_issues for ref in issue.evidence_refs),
            ]
            if any(ref not in self.evidence_refs for ref in summary_evidence):
                raise ValueError("evidence_refs must preserve summary and unified issue evidence")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be UTC")
        return self


class StoryBibleCuratorProposalV1(StrictBaseModel):
    """Proposal-only output returned by the StoryBible Curator."""

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: StoryBibleId
    project_id: StoryBibleId
    status: RecordStatus = RecordStatus.CANDIDATE
    commit_plan: CommitPlanV1
    conflicts: list[ConflictV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @field_validator("proposal_id", "project_id")
    @classmethod
    def identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleProductionRunStatus(StrEnum):
    """Execution-only lifecycle for one production curator checkpoint."""

    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class StoryBibleProductionFailureStage(StrEnum):
    """Sanitized execution boundary at which production curation stopped."""

    INPUT_ADAPTATION = "INPUT_ADAPTATION"
    CONTEXT_BUDGET = "CONTEXT_BUDGET"
    PROVIDER = "PROVIDER"
    SCHEMA = "SCHEMA"
    NORMALIZATION = "NORMALIZATION"
    AGENT_RUN_PERSISTENCE = "AGENT_RUN_PERSISTENCE"
    RUN_CHECKPOINT_PERSISTENCE = "RUN_CHECKPOINT_PERSISTENCE"


class StoryBibleProductionAuthorizationKind(StrEnum):
    """Authority used to supply non-canonical material to production curation."""

    LEGACY_APPROVED = "LEGACY_APPROVED"
    HUMAN_APPROVED = "HUMAN_APPROVED"


class StoryBibleProductionAuthorizationPolicy(StrEnum):
    """Whether a production coordinator may accept legacy approved inputs."""

    HUMAN_APPROVED_ONLY = "HUMAN_APPROVED_ONLY"
    LEGACY_COMPAT = "LEGACY_COMPAT"


class StoryBibleProductionAuthorizationFailureCode(StrEnum):
    """Safe business outcome for a production request lacking authorization."""

    PRODUCTION_AUTHORIZATION_REQUIRED = "PRODUCTION_AUTHORIZATION_REQUIRED"


class StoryBibleProductionAuthorizationFailureV1(StrictBaseModel):
    """Structured refusal returned before a Curator or provider can run."""

    schema_version: Literal["1.0"] = "1.0"
    code: StoryBibleProductionAuthorizationFailureCode
    authorization_policy: StoryBibleProductionAuthorizationPolicy


class HumanApprovedStoryBibleProductionLineageV1(StrictBaseModel):
    """Human-review provenance carried by a production execution checkpoint."""

    schema_version: Literal["1.0"] = "1.0"
    human_review_id: StoryBibleId
    dossier_id: StoryBibleId
    narrative_execution_bundle_id: StoryBibleId
    timeline_review_material_id: StoryBibleId

    @field_validator(
        "human_review_id",
        "dossier_id",
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
    )
    @classmethod
    def lineage_ids_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class HumanApprovedStoryBibleProductionExecutionFailureCode(StrEnum):
    """Business outcomes before a human-approved context reaches a Coordinator."""

    HUMAN_REVIEW_NOT_APPROVED = "HUMAN_REVIEW_NOT_APPROVED"
    INVALID_HUMAN_APPROVED_CONTEXT = "INVALID_HUMAN_APPROVED_CONTEXT"
    PRODUCTION_RESERVATION_FAILED = "PRODUCTION_RESERVATION_FAILED"
    REPOSITORY_CONFLICT = "REPOSITORY_CONFLICT"


class StoryBibleProductionInputV1(StrictBaseModel):
    """Server-built production references; v1.2 separates human from legacy lineage."""

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId | None = None
    approved_timeline_bundle_id: StoryBibleId | None = None
    human_review_id: StoryBibleId | None = None
    production_dossier_id: StoryBibleId | None = None
    narrative_execution_bundle_id: StoryBibleId | None = None
    timeline_review_material_id: StoryBibleId | None = None
    canonical_storybible_snapshot_hash: StoryBibleId
    authorization_kind: StoryBibleProductionAuthorizationKind = (
        StoryBibleProductionAuthorizationKind.LEGACY_APPROVED
    )
    human_approved_lineage: HumanApprovedStoryBibleProductionLineageV1 | None = None

    @field_validator(
        "project_id",
        "canonical_storybible_snapshot_hash",
    )
    @classmethod
    def production_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_input_authorization(self) -> "StoryBibleProductionInputV1":
        if self.authorization_kind == StoryBibleProductionAuthorizationKind.LEGACY_APPROVED:
            if self.human_approved_lineage is not None:
                raise ValueError("legacy production input cannot contain human-review lineage")
            if self.gate2_approved_bundle_id is None or self.approved_timeline_bundle_id is None:
                raise ValueError("legacy production input requires approved bundle ids")
            if any(
                value is not None
                for value in (
                    self.human_review_id,
                    self.production_dossier_id,
                    self.narrative_execution_bundle_id,
                    self.timeline_review_material_id,
                )
            ):
                raise ValueError("legacy production input cannot contain human-approved ids")
        else:
            lineage = self.human_approved_lineage
            if lineage is None:
                raise ValueError("human-approved production input requires human-review lineage")
            if (
                self.gate2_approved_bundle_id is not None
                or self.approved_timeline_bundle_id is not None
            ):
                raise ValueError("human-approved production input cannot write legacy bundle ids")
            if (
                self.human_review_id != lineage.human_review_id
                or self.production_dossier_id != lineage.dossier_id
                or self.narrative_execution_bundle_id != lineage.narrative_execution_bundle_id
                or self.timeline_review_material_id != lineage.timeline_review_material_id
            ):
                raise ValueError(
                    "human-approved production input has inconsistent material lineage"
                )
        return self


class StoryBibleProductionInputFailureCode(StrEnum):
    HUMAN_REVIEW_NOT_APPROVED = "HUMAN_REVIEW_NOT_APPROVED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    INVALID_DOSSIER_LINEAGE = "INVALID_DOSSIER_LINEAGE"


class StoryBibleProductionInputV2(StrictBaseModel):
    """Human-approved, non-executing handoff contract for future production."""

    schema_version: Literal["2.0"] = "2.0"
    project_id: StoryBibleId
    human_review_id: StoryBibleId
    human_review_decision: Literal["APPROVE"]
    reviewer_id: StoryBibleId
    review_time: datetime
    dossier_id: StoryBibleId
    narrative_execution_bundle_id: StoryBibleId
    timeline_review_material_id: StoryBibleId
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    dossier_provenance: ProductionDossierProvenanceV1

    @field_validator(
        "project_id",
        "human_review_id",
        "reviewer_id",
        "dossier_id",
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
    )
    @classmethod
    def v2_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def v2_lineage_is_complete(self) -> "StoryBibleProductionInputV2":
        if self.review_time.tzinfo is None or self.review_time.utcoffset() != timedelta(0):
            raise ValueError("review_time must be UTC")
        if not self.dossier_provenance.narrative_analysis_run_id:
            raise ValueError("dossier provenance requires narrative analysis lineage")
        return self


class StoryBibleProductionInputBuildResultV1(StrictBaseModel):
    """Structured business result; this builder never invokes production."""

    schema_version: Literal["1.0", "1.1"] = "1.0"
    production_input: StoryBibleProductionInputV2 | None = None
    failure_code: StoryBibleProductionInputFailureCode | None = None

    @model_validator(mode="after")
    def result_is_exactly_one_business_outcome(self) -> "StoryBibleProductionInputBuildResultV1":
        if (self.production_input is None) == (self.failure_code is None):
            raise ValueError("build result requires exactly one input or failure code")
        return self


class StoryBibleCanonicalSnapshotV1(StrictBaseModel):
    """Deterministically ordered canonical StoryBible state used by production."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    profiles: list[StoryEntityProfileV1] = Field(default_factory=list)
    states: list[StoryEntityStateV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def snapshot_project_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_snapshot_scope_and_order(self) -> "StoryBibleCanonicalSnapshotV1":
        collections = (
            (self.profiles, "profile_id"),
            (self.states, "state_id"),
            (self.relationships, "relationship_id"),
            (self.world_rules, "rule_id"),
        )
        for resources, id_field in collections:
            if any(resource.project_id != self.project_id for resource in resources):
                raise ValueError("canonical snapshot resources must belong to its project")
            ids = [getattr(resource, id_field) for resource in resources]
            if ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError("canonical snapshot resources must be unique and id-sorted")
        return self


class StoryBibleTrustedEventOrderV1(StrictBaseModel):
    """Approved strict predecessors and an order only when they form a total order."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: StoryBibleId
    strict_predecessor_event_ids: list[StoryBibleId] = Field(default_factory=list)
    resolved_order: int | None = Field(default=None, ge=0)

    @field_validator("event_id")
    @classmethod
    def event_id_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_predecessors(self) -> "StoryBibleTrustedEventOrderV1":
        if self.event_id in self.strict_predecessor_event_ids:
            raise ValueError("event cannot precede itself")
        if self.strict_predecessor_event_ids != sorted(self.strict_predecessor_event_ids):
            raise ValueError("strict predecessor ids must be sorted")
        if len(self.strict_predecessor_event_ids) != len(set(self.strict_predecessor_event_ids)):
            raise ValueError("strict predecessor ids must be unique")
        return self


class StoryBibleProductionContextV1(StrictBaseModel):
    """Server-built trusted context derived from authorized persisted artifacts."""

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId | None = None
    narrative_analysis_run_id: StoryBibleId
    approved_timeline_bundle_id: StoryBibleId | None = None
    timeline_run_id: StoryBibleId
    human_review_id: StoryBibleId | None = None
    production_dossier_id: StoryBibleId | None = None
    narrative_execution_bundle_id: StoryBibleId | None = None
    timeline_review_material_id: StoryBibleId | None = None
    approved_entities: list[EntityProposalV1] = Field(default_factory=list)
    approved_events: list[EventProposalV1] = Field(default_factory=list)
    approved_state_changes: list[StateChangeProposalV1] = Field(default_factory=list)
    approved_temporal_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    trusted_event_ids: list[StoryBibleId] = Field(default_factory=list)
    trusted_event_order: list[StoryBibleTrustedEventOrderV1] = Field(default_factory=list)
    trusted_evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list)
    source_chunks: list[SourceChunkV1] = Field(default_factory=list)
    canonical_snapshot: StoryBibleCanonicalSnapshotV1
    canonical_storybible_snapshot_hash: StoryBibleId
    authorization_kind: StoryBibleProductionAuthorizationKind = (
        StoryBibleProductionAuthorizationKind.LEGACY_APPROVED
    )
    human_approved_lineage: HumanApprovedStoryBibleProductionLineageV1 | None = None

    @field_validator(
        "project_id",
        "narrative_analysis_run_id",
        "timeline_run_id",
        "canonical_storybible_snapshot_hash",
    )
    @classmethod
    def context_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_trusted_context(self) -> "StoryBibleProductionContextV1":
        if self.canonical_snapshot.project_id != self.project_id:
            raise ValueError("canonical snapshot must belong to the context project")
        if self.trusted_event_ids != sorted(self.trusted_event_ids) or len(
            self.trusted_event_ids
        ) != len(set(self.trusted_event_ids)):
            raise ValueError("trusted event ids must be unique and sorted")
        approved_event_ids = {event.proposal_id for event in self.approved_events}
        if set(self.trusted_event_ids) != approved_event_ids:
            raise ValueError("trusted event ids must exactly match approved events")
        order_ids = [item.event_id for item in self.trusted_event_order]
        if order_ids != self.trusted_event_ids:
            raise ValueError("trusted event order must cover trusted events in id order")
        if any(
            not set(item.strict_predecessor_event_ids).issubset(approved_event_ids)
            for item in self.trusted_event_order
        ):
            raise ValueError("event order references an untrusted event")
        if self.source_chunk_ids != sorted(self.source_chunk_ids) or len(
            self.source_chunk_ids
        ) != len(set(self.source_chunk_ids)):
            raise ValueError("source chunk ids must be unique and sorted")
        if {ref.chunk_id for ref in self.trusted_evidence_refs} != set(self.source_chunk_ids):
            raise ValueError("source chunk ids must exactly match trusted evidence")
        chunk_ids = [chunk.chunk_id for chunk in self.source_chunks]
        if chunk_ids != self.source_chunk_ids:
            raise ValueError("source chunks must cover trusted chunk ids in id order")
        if any(chunk.project_id != self.project_id for chunk in self.source_chunks):
            raise ValueError("source chunks must belong to the context project")
        if self.authorization_kind == StoryBibleProductionAuthorizationKind.LEGACY_APPROVED:
            if self.human_approved_lineage is not None:
                raise ValueError("legacy production context cannot contain human-review lineage")
            if self.gate2_approved_bundle_id is None or self.approved_timeline_bundle_id is None:
                raise ValueError("legacy production context requires approved bundle ids")
        else:
            lineage = self.human_approved_lineage
            if lineage is None:
                raise ValueError("human-approved production context requires human-review lineage")
            if (
                self.gate2_approved_bundle_id is not None
                or self.approved_timeline_bundle_id is not None
            ):
                raise ValueError("human-approved production context cannot write legacy bundle ids")
            if (
                self.human_review_id != lineage.human_review_id
                or self.production_dossier_id != lineage.dossier_id
                or self.narrative_execution_bundle_id != lineage.narrative_execution_bundle_id
                or self.timeline_review_material_id != lineage.timeline_review_material_id
            ):
                raise ValueError(
                    "human-approved production context has inconsistent material lineage"
                )
        return self


class HumanApprovedStoryBibleProductionContextV1(StrictBaseModel):
    """Production context authorized by a unified human APPROVE decision.

    This is an input-boundary artifact only. It does not authorize canonical
    writes or invoke a Curator.
    """

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    human_review_id: StoryBibleId
    human_review_decision: Literal["APPROVE"]
    reviewer_id: StoryBibleId
    review_time: datetime
    dossier_id: StoryBibleId
    narrative_execution_bundle_id: StoryBibleId
    timeline_review_material_id: StoryBibleId
    narrative_analysis_run_id: StoryBibleId
    timeline_run_id: StoryBibleId
    human_approved_entities: list[EntityProposalV1] = Field(default_factory=list)
    human_approved_events: list[EventProposalV1] = Field(default_factory=list)
    human_approved_state_changes: list[StateChangeProposalV1] = Field(default_factory=list)
    human_approved_temporal_relations: list[TemporalRelationProposalV1] = Field(
        default_factory=list
    )
    narrative_execution_status: NarrativeExecutionStatus
    narrative_issues: list[ReviewIssueV1] = Field(default_factory=list)
    excluded_items: list[NarrativeExecutionExcludedItemV1] = Field(default_factory=list)
    failed_windows: list[NarrativeExecutionFailedWindowV1] = Field(default_factory=list)
    timeline_review_status: ReviewGate3Decision
    timeline_issues: list[TimelineGate3IssueV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    source_chunk_ids: list[StoryBibleId] = Field(default_factory=list)
    source_chunks: list[SourceChunkV1] = Field(default_factory=list)
    canonical_snapshot: StoryBibleCanonicalSnapshotV1

    @field_validator(
        "project_id",
        "human_review_id",
        "reviewer_id",
        "dossier_id",
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
        "narrative_analysis_run_id",
        "timeline_run_id",
    )
    @classmethod
    def human_context_ids_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_human_context_lineage(self) -> "HumanApprovedStoryBibleProductionContextV1":
        if self.review_time.tzinfo is None or self.review_time.utcoffset() != timedelta(0):
            raise ValueError("review_time must be UTC")
        if self.canonical_snapshot.project_id != self.project_id:
            raise ValueError("canonical snapshot must belong to the human-approved context project")
        event_ids = {event.proposal_id for event in self.human_approved_events}
        relation_event_ids = {
            event_id
            for relation in self.human_approved_temporal_relations
            for event_id in (relation.source_event_id, relation.target_event_id)
        }
        if not relation_event_ids.issubset(event_ids):
            raise ValueError(
                "human-approved Timeline relations must reference human-approved events"
            )
        if len({entity.proposal_id for entity in self.human_approved_entities}) != len(
            self.human_approved_entities
        ):
            raise ValueError("human-approved entity ids must be unique")
        if len(event_ids) != len(self.human_approved_events):
            raise ValueError("human-approved event ids must be unique")
        if len({change.proposal_id for change in self.human_approved_state_changes}) != len(
            self.human_approved_state_changes
        ):
            raise ValueError("human-approved state-change ids must be unique")
        if any(chunk.project_id != self.project_id for chunk in self.source_chunks):
            raise ValueError("source chunks must belong to the human-approved context project")
        source_ids = [chunk.chunk_id for chunk in self.source_chunks]
        if (
            source_ids != self.source_chunk_ids
            or source_ids != sorted(source_ids)
            or len(source_ids) != len(set(source_ids))
        ):
            raise ValueError("source chunks must exactly match ordered source_chunk_ids")
        if any(ref.chunk_id not in set(source_ids) for ref in self.evidence_refs):
            raise ValueError("source chunks must cover human-approved evidence references")
        return self


class StoryBibleProductionRunV1(StrictBaseModel):
    """Durable, resumable execution checkpoint for production StoryBible curation."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.1"
    run_id: StoryBibleId
    project_id: StoryBibleId
    gate2_approved_bundle_id: StoryBibleId | None = None
    approved_timeline_bundle_id: StoryBibleId | None = None
    human_review_id: StoryBibleId | None = None
    production_dossier_id: StoryBibleId | None = None
    narrative_execution_bundle_id: StoryBibleId | None = None
    timeline_review_material_id: StoryBibleId | None = None
    canonical_storybible_snapshot_hash: StoryBibleId
    input_hash: StoryBibleId
    model_identity: StoryBibleName
    status: StoryBibleProductionRunStatus
    curator_proposal: StoryBibleCuratorProposalV1 | None = None
    agent_run_id: StoryBibleId | None = None
    provider_request_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    failure_stage: StoryBibleProductionFailureStage | None = None
    authorization_kind: StoryBibleProductionAuthorizationKind = (
        StoryBibleProductionAuthorizationKind.LEGACY_APPROVED
    )
    human_approved_lineage: HumanApprovedStoryBibleProductionLineageV1 | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "run_id",
        "project_id",
        "canonical_storybible_snapshot_hash",
        "input_hash",
        "model_identity",
    )
    @classmethod
    def run_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("error_message")
    @classmethod
    def error_is_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            return _reject_blank(value)
        return value

    @model_validator(mode="after")
    def validate_execution_checkpoint(self) -> "StoryBibleProductionRunV1":
        if self.status == StoryBibleProductionRunStatus.SUCCEEDED:
            if self.curator_proposal is None or self.agent_run_id is None:
                raise ValueError("SUCCEEDED run requires curator_proposal and agent_run_id")
            if self.provider_request_count < 1:
                raise ValueError("SUCCEEDED run requires a provider request")
            if self.curator_proposal.project_id != self.project_id:
                raise ValueError("curator proposal must belong to the run project")
        elif self.curator_proposal is not None:
            raise ValueError("only SUCCEEDED runs may contain curator output")
        elif self.agent_run_id is not None and self.status != StoryBibleProductionRunStatus.FAILED:
            raise ValueError("only terminal runs may contain AgentRun provenance")
        if self.status == StoryBibleProductionRunStatus.FAILED:
            if self.error_message is None:
                raise ValueError("FAILED run requires error_message")
        elif self.error_message is not None or self.failure_stage is not None:
            raise ValueError("only FAILED runs may contain failure details")
        if self.status == StoryBibleProductionRunStatus.RESERVED and self.provider_request_count:
            raise ValueError("RESERVED run cannot contain provider requests")
        if self.authorization_kind == StoryBibleProductionAuthorizationKind.LEGACY_APPROVED:
            if self.human_approved_lineage is not None:
                raise ValueError("legacy production run cannot contain human-review lineage")
            if self.gate2_approved_bundle_id is None or self.approved_timeline_bundle_id is None:
                raise ValueError("legacy production run requires approved bundle ids")
        else:
            lineage = self.human_approved_lineage
            if lineage is None:
                raise ValueError("human-approved production run requires human-review lineage")
            if (
                self.gate2_approved_bundle_id is not None
                or self.approved_timeline_bundle_id is not None
            ):
                raise ValueError("human-approved production run cannot write legacy bundle ids")
            if (
                self.human_review_id != lineage.human_review_id
                or self.production_dossier_id != lineage.dossier_id
                or self.narrative_execution_bundle_id != lineage.narrative_execution_bundle_id
                or self.timeline_review_material_id != lineage.timeline_review_material_id
            ):
                raise ValueError("human-approved production run has inconsistent material lineage")
        return self


class ComicPlanningInputV1(StrictBaseModel):
    """Stable, proposal-only handoff from a completed human-approved production run.

    This contract does not create scenes, panels, images, or canonical StoryBible
    data.  It gives a future Comic Planning stage one typed source of lineage and
    evidence without reading the production database directly.
    """

    schema_version: Literal["1.0"] = "1.0"
    project_id: StoryBibleId
    storybible_production_run_id: StoryBibleId
    human_review_id: StoryBibleId
    production_dossier_id: StoryBibleId
    canonical_storybible_snapshot_hash: StoryBibleId
    curator_proposal_id: StoryBibleId
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)

    @field_validator(
        "project_id",
        "storybible_production_run_id",
        "human_review_id",
        "production_dossier_id",
        "canonical_storybible_snapshot_hash",
        "curator_proposal_id",
    )
    @classmethod
    def comic_planning_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class StoryBibleReviewDecision(StrEnum):
    """Deterministic disposition of an existing StoryBible proposal."""

    APPROVE = "APPROVE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    REJECT = "REJECT"


class StoryBibleReviewIssueSeverity(StrEnum):
    """Impact of a deterministic StoryBible review issue."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKING = "BLOCKING"


class StoryBibleReviewIssueV1(StrictBaseModel):
    """Structured diagnostic found while reviewing proposal-owned facts."""

    schema_version: Literal["1.0"] = "1.0"
    issue_id: StoryBibleId
    category: StoryBibleName
    severity: StoryBibleReviewIssueSeverity
    message: str
    affected_ids: list[StoryBibleId] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)

    @field_validator("issue_id", "category", "message")
    @classmethod
    def issue_text_is_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("affected_ids")
    @classmethod
    def affected_ids_are_unique_and_sorted(cls, value: list[str]) -> list[str]:
        if value != sorted(value) or len(value) != len(set(value)):
            raise ValueError("affected_ids must be unique and sorted")
        return value


class StoryBibleEvidenceCheckV1(StrictBaseModel):
    """Deterministic grounding outcome for one proposal evidence reference."""

    schema_version: Literal["1.0"] = "1.0"
    check_id: StoryBibleId
    owner_id: StoryBibleId
    evidence_ref: EvidenceRefV1
    valid: bool
    message: str | None = None

    @field_validator("check_id", "owner_id")
    @classmethod
    def check_identifiers_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def invalid_check_has_message(self) -> "StoryBibleEvidenceCheckV1":
        if not self.valid and self.message is None:
            raise ValueError("invalid evidence check requires a message")
        if self.message is not None:
            self.message = _reject_blank(self.message)
        return self


class StoryBibleReviewResultV1(StrictBaseModel):
    """Deterministic audit of exactly one persisted StoryBible production run."""

    schema_version: Literal["1.0"] = "1.0"
    review_id: StoryBibleId
    project_id: StoryBibleId
    storybible_run_id: StoryBibleId
    proposal_hash: StoryBibleId
    decision: StoryBibleReviewDecision
    issues: list[StoryBibleReviewIssueV1] = Field(default_factory=list)
    evidence_checks: list[StoryBibleEvidenceCheckV1] = Field(default_factory=list)
    validated_entities: list[StoryBibleId] = Field(default_factory=list)
    validated_relationships: list[StoryBibleId] = Field(default_factory=list)
    validated_world_rules: list[StoryBibleId] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("review_id", "project_id", "storybible_run_id", "proposal_hash")
    @classmethod
    def review_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("validated_entities", "validated_relationships", "validated_world_rules")
    @classmethod
    def validated_ids_are_unique_and_sorted(cls, value: list[str]) -> list[str]:
        if value != sorted(value) or len(value) != len(set(value)):
            raise ValueError("validated resource ids must be unique and sorted")
        return value

    @model_validator(mode="after")
    def decision_matches_issues(self) -> "StoryBibleReviewResultV1":
        has_blocking = any(
            issue.severity == StoryBibleReviewIssueSeverity.BLOCKING for issue in self.issues
        )
        has_review_required = any(
            issue.severity == StoryBibleReviewIssueSeverity.REVIEW_REQUIRED for issue in self.issues
        )
        if self.decision == StoryBibleReviewDecision.APPROVE and self.issues:
            raise ValueError("APPROVE review cannot contain issues")
        if self.decision == StoryBibleReviewDecision.REJECT and not has_blocking:
            raise ValueError("REJECT review requires a blocking issue")
        if self.decision == StoryBibleReviewDecision.NEEDS_HUMAN_REVIEW and (
            has_blocking or not has_review_required
        ):
            raise ValueError("NEEDS_HUMAN_REVIEW requires non-blocking review-required issues")
        return self


class StoryBibleReviewContextV1(StrictBaseModel):
    """Server-owned immutable inputs needed to run one deterministic review."""

    schema_version: Literal["1.0"] = "1.0"
    review_id: StoryBibleId
    project_id: StoryBibleId
    source_storybible_run_id: StoryBibleId
    source_approved_timeline_bundle_id: StoryBibleId
    canonical_snapshot: StoryBibleCanonicalSnapshotV1
    canonical_snapshot_hash: StoryBibleId
    proposal_hash: StoryBibleId
    reviewed_at: datetime

    @field_validator(
        "review_id",
        "project_id",
        "source_storybible_run_id",
        "source_approved_timeline_bundle_id",
        "canonical_snapshot_hash",
        "proposal_hash",
    )
    @classmethod
    def context_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_context_snapshot(self) -> "StoryBibleReviewContextV1":
        if self.canonical_snapshot.project_id != self.project_id:
            raise ValueError("review canonical snapshot belongs to another project")
        return self


class StoryBibleReviewMetadataV1(StrictBaseModel):
    """Review and lineage metadata carried into the frozen bundle."""

    schema_version: Literal["1.0"] = "1.0"
    review_id: StoryBibleId
    decision: Literal[StoryBibleReviewDecision.APPROVE]
    proposal_hash: StoryBibleId
    source_approved_timeline_bundle_id: StoryBibleId
    reviewed_at: datetime
    frozen_at: datetime

    @field_validator("review_id", "proposal_hash", "source_approved_timeline_bundle_id")
    @classmethod
    def metadata_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)


class ApprovedStoryBibleBundleV1(StrictBaseModel):
    """Immutable, reviewed StoryBible snapshot trusted by comic planning."""

    schema_version: Literal["1.0"] = "1.0"
    bundle_id: StoryBibleId
    project_id: StoryBibleId
    source_storybible_run_id: StoryBibleId
    snapshot_hash: StoryBibleId
    entities: list[StoryEntityProfileV1] = Field(default_factory=list)
    relationships: list[StoryRelationshipV1] = Field(default_factory=list)
    world_rules: list[WorldRuleV1] = Field(default_factory=list)
    state_changes: list[StoryEntityStateV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    review_metadata: StoryBibleReviewMetadataV1

    @field_validator("bundle_id", "project_id", "source_storybible_run_id", "snapshot_hash")
    @classmethod
    def bundle_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_canonical_bundle(self) -> "ApprovedStoryBibleBundleV1":
        collections = (
            (self.entities, "profile_id"),
            (self.relationships, "relationship_id"),
            (self.world_rules, "rule_id"),
            (self.state_changes, "state_id"),
        )
        for resources, id_field in collections:
            if any(resource.project_id != self.project_id for resource in resources):
                raise ValueError("approved StoryBible resources must belong to its project")
            ids = [getattr(resource, id_field) for resource in resources]
            if ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError("approved StoryBible resources must be unique and id-sorted")
        entity_ids = {entity.profile_id for entity in self.entities}
        if any(
            relationship.source_profile_id not in entity_ids
            or relationship.target_profile_id not in entity_ids
            for relationship in self.relationships
        ):
            raise ValueError("approved relationships must reference bundled entities")
        if any(state.profile_id not in entity_ids for state in self.state_changes):
            raise ValueError("approved state changes must reference bundled entities")
        return self


class StoryBibleReviewRunStatus(StrEnum):
    """Persistence lifecycle independent of StoryBible production execution."""

    REVIEWED = "REVIEWED"
    FROZEN = "FROZEN"


class StoryBibleReviewRunV1(StrictBaseModel):
    """Durable review result and optional insert-once frozen bundle."""

    schema_version: Literal["1.0"] = "1.0"
    review_id: StoryBibleId
    project_id: StoryBibleId
    source_storybible_run_id: StoryBibleId
    source_approved_timeline_bundle_id: StoryBibleId
    canonical_snapshot: StoryBibleCanonicalSnapshotV1
    canonical_snapshot_hash: StoryBibleId
    proposal_hash: StoryBibleId
    status: StoryBibleReviewRunStatus = StoryBibleReviewRunStatus.REVIEWED
    review_result: StoryBibleReviewResultV1
    approved_bundle: ApprovedStoryBibleBundleV1 | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    frozen_at: datetime | None = None

    @field_validator(
        "review_id",
        "project_id",
        "source_storybible_run_id",
        "source_approved_timeline_bundle_id",
        "canonical_snapshot_hash",
        "proposal_hash",
    )
    @classmethod
    def persisted_review_references_are_not_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @model_validator(mode="after")
    def validate_review_checkpoint(self) -> "StoryBibleReviewRunV1":
        result = self.review_result
        if (
            result.review_id != self.review_id
            or result.project_id != self.project_id
            or result.storybible_run_id != self.source_storybible_run_id
            or result.proposal_hash != self.proposal_hash
        ):
            raise ValueError("persisted review metadata does not match review result")
        if self.status == StoryBibleReviewRunStatus.REVIEWED:
            if self.approved_bundle is not None or self.frozen_at is not None:
                raise ValueError("REVIEWED run cannot contain a frozen bundle")
        else:
            if result.decision != StoryBibleReviewDecision.APPROVE:
                raise ValueError("only an APPROVE review may be frozen")
            if self.approved_bundle is None or self.frozen_at is None:
                raise ValueError("FROZEN run requires an approved bundle and frozen_at")
            if (
                self.approved_bundle.project_id != self.project_id
                or self.approved_bundle.source_storybible_run_id != self.source_storybible_run_id
                or self.approved_bundle.review_metadata.review_id != self.review_id
                or self.approved_bundle.review_metadata.proposal_hash != self.proposal_hash
                or self.approved_bundle.review_metadata.source_approved_timeline_bundle_id
                != self.source_approved_timeline_bundle_id
                or self.approved_bundle.review_metadata.reviewed_at != result.reviewed_at
                or self.approved_bundle.review_metadata.frozen_at != self.frozen_at
            ):
                raise ValueError("frozen bundle lineage does not match its review run")
        return self
