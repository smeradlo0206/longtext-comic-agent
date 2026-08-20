"""Workflow run schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel
from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    RelationshipSignalProposalV1,
    StateChangeProposalV1,
)
from comic_agent.schemas.recovery import RecoveryOutcomeV1
from comic_agent.schemas.review import NarrativeAnalysisReviewRouteV1, ReviewGate2ResultV1


class AgentRunStatus(StrEnum):
    """Allowed lifecycle states for one agent execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class NarrativeAnalysisRunStatus(StrEnum):
    """Lifecycle states for a whole-document narrative analysis task."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


class NarrativeAnalysisWindowStatus(StrEnum):
    """Lifecycle states for one bounded analysis window."""

    PENDING = "PENDING"
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    REVIEWING = "REVIEWING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"
    SPLIT = "SPLIT"


class NarrativeAnalysisBatchStatus(StrEnum):
    """Source-free lifecycle state for a bounded document batch."""

    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"


class NarrativeGate2HandoffStatus(StrEnum):
    """Durable state of the deterministic post-Narrative Gate 2 handoff."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProviderType(StrEnum):
    """Provider execution family."""

    MOCK = "MOCK"
    LLM = "LLM"
    IMAGE = "IMAGE"


class WorkflowRunV1(StrictBaseModel):
    """Minimal workflow run record."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    workflow_run_id: str = Field(description="Workflow run id.")
    project_id: str = Field(description="Project id.")
    status: str = Field(description="Run status.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Unstable workflow payload.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Created at.",
    )


class NarrativeAnalysisWindowPlanV1(StrictBaseModel):
    """Deterministic source chunk window planned before execution."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"] = Field(
        default="1.4",
        description=(
            "Schema version. Historical 1.0 through 1.3 records remain readable; "
            "1.4 adds deterministic output ownership; 1.5 adds execution checkpoints; "
            "1.6 adds batch budgets; 1.7 adds bounded split-recovery accounting."
        ),
    )
    window_index: int = Field(ge=0, description="Zero-based window sequence.")
    chunk_ids: list[str] = Field(min_length=1, description="Ordered source chunk ids.")
    owned_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Source chunks whose proposals this window exclusively owns.",
    )


class NarrativeAnalysisWindowV1(NarrativeAnalysisWindowPlanV1):
    """Auditable state for one mode over one planned source window."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7"] = Field(
        default="1.7",
        description=(
            "Schema version. Historical 1.0 through 1.3 window records remain readable; "
            "1.5 adds source-free retry scheduling and Provider checkpoints; 1.6 adds "
            "planned batch and execution-budget audit fields; 1.7 adds bounded "
            "split-recovery accounting."
        ),
    )

    analysis_window_id: str = Field(description="Persistent analysis window id.")
    analysis_run_id: str = Field(description="Owning whole-document analysis run id.")
    mode: str = Field(description="NarrativeAnalyst mode.")
    status: NarrativeAnalysisWindowStatus = Field(description="Window execution status.")
    agent_run_id: str | None = Field(
        default=None, description="Persisted AgentRun id when executed."
    )
    error_message: str | None = Field(default=None, description="Sanitized failure reason.")
    failure_category: str | None = Field(
        default=None,
        description="Sanitized failure category for a failed window.",
    )
    recommended_action: str | None = Field(
        default=None,
        description="Sanitized operator guidance for a failed window.",
    )
    provider_error_diagnostics: dict[str, Any] | None = Field(
        default=None,
        description="Whitelisted provider diagnostics without response content.",
    )
    attempt_count: int = Field(
        default=0,
        ge=0,
        description="Completed execution attempts for this window.",
    )
    effective_max_chars_per_chunk: int = Field(
        default=1200,
        ge=1,
        description="Bounded source-text budget used by the latest attempt.",
    )
    previous_failure_category: str | None = Field(
        default=None,
        description="Failure category that triggered the current retry policy.",
    )
    parent_window_id: str | None = Field(
        default=None,
        description="Parent window id for a deterministic split child.",
    )
    split_reason: str | None = Field(
        default=None,
        description="Sanitized reason recorded when this window is split.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Stable execution identity for this exact mode/window/scope.",
    )
    batch_id: str | None = Field(
        default=None,
        description="Stable parent batch id; absent on historical records.",
    )
    estimated_input_chars: int = Field(
        default=0,
        ge=0,
        description="Conservative source-character estimate; never exact token accounting.",
    )
    estimated_input_tokens: int = Field(
        default=0,
        ge=0,
        description="Conservative estimated input-token budget for this window.",
    )
    output_token_budget: int = Field(
        default=2000,
        ge=1,
        description="Configured upper bound for structured Provider output tokens.",
    )
    time_budget_seconds: int = Field(
        default=300,
        ge=1,
        description="Configured elapsed-time budget for this window's controlled attempts.",
    )
    max_call_attempts: int = Field(
        default=2,
        ge=1,
        description="Configured maximum Provider calls for this exact window.",
    )
    max_split_depth: int = Field(
        default=1,
        ge=0,
        le=8,
        description="Maximum deterministic source-boundary split depth for this window tree.",
    )
    split_depth: int = Field(
        default=0,
        ge=0,
        le=8,
        description="Current deterministic split depth; zero denotes an original planned window.",
    )
    provider_request_count: int = Field(
        default=0,
        ge=0,
        description="Persisted Provider invocations consumed by this exact window.",
    )
    elapsed_seconds_used: int = Field(
        default=0,
        ge=0,
        description="Ceiling-rounded Provider elapsed time consumed by this exact window.",
    )
    output_tokens_used: int = Field(
        default=0,
        ge=0,
        description="Provider-reported output tokens when available; zero means unavailable.",
    )
    next_eligible_retry_at: datetime | None = Field(
        default=None,
        description="Source-free earliest time for a bounded retry.",
    )
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    @model_validator(mode="after")
    def normalize_owned_chunk_ids(self) -> "NarrativeAnalysisWindowV1":
        if not self.owned_chunk_ids:
            self.owned_chunk_ids = list(self.chunk_ids)
        if len(self.owned_chunk_ids) != len(set(self.owned_chunk_ids)):
            raise ValueError("owned_chunk_ids must be unique")
        if not set(self.owned_chunk_ids).issubset(self.chunk_ids):
            raise ValueError("owned_chunk_ids must be a subset of chunk_ids")
        if self.split_depth > self.max_split_depth:
            raise ValueError("split_depth must not exceed max_split_depth")
        return self


class NarrativeAnalysisBatchV1(StrictBaseModel):
    """Stable, source-free manifest for one bounded segment of a document run."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    batch_id: str = Field(description="Persistent stable batch id.")
    analysis_run_id: str = Field(description="Owning Narrative analysis run id.")
    document_id: str = Field(description="Source document identifier.")
    chunk_ids: list[str] = Field(min_length=1, description="Ordered approved SourceChunk ids.")
    status: NarrativeAnalysisBatchStatus = Field(default=NarrativeAnalysisBatchStatus.PLANNED)
    idempotency_key: str = Field(description="Stable identity for this exact batch scope.")
    estimated_input_chars: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    output_token_budget: int = Field(ge=1)
    time_budget_seconds: int = Field(ge=1)
    max_call_attempts: int = Field(ge=1)


class NarrativeGate2HandoffV1(StrictBaseModel):
    """Source-free, resumable checkpoint for one root run's Gate 2 completion."""

    schema_version: Literal["1.0"] = Field(default="1.0")
    status: NarrativeGate2HandoffStatus = Field(default=NarrativeGate2HandoffStatus.PENDING)
    attempt_count: int = Field(default=0, ge=0, le=2)
    max_attempts: int = Field(default=2, ge=1, le=2)
    safe_issue_codes: list[str] = Field(default_factory=list)
    failure_category: str | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class NarrativeAnalysisRunV1(StrictBaseModel):
    """Persistent, resumable whole-document NarrativeAnalyst task."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"] = Field(
        default="1.5",
        description=(
            "Schema version; v1.0/v1.1 records remain readable and v1.2 adds "
            "source-free recovery outcomes; v1.3 adds deterministic batch manifests; "
            "v1.4 adds root execution-budget reservations; v1.5 adds a durable Gate 2 handoff."
        ),
    )
    analysis_run_id: str = Field(description="Persistent analysis task id.")
    project_id: str = Field(description="Owning project id.")
    document_id: str = Field(description="Selected source document id.")
    modes: list[str] = Field(min_length=1, description="Independent modes selected for the task.")
    status: NarrativeAnalysisRunStatus = Field(description="Whole-document task status.")
    window_size: int = Field(default=3, ge=1, description="Maximum chunks per window.")
    stride: int = Field(default=2, ge=1, description="Chunk offset between windows.")
    concurrency: Literal[1] = Field(default=1, description="Initial worker concurrency.")
    real_llm_requested: bool = Field(
        default=False, description="Explicit request-level real LLM opt-in."
    )
    window_ids: list[str] = Field(default_factory=list, description="Persistent window record ids.")
    batches: list[NarrativeAnalysisBatchV1] = Field(
        default_factory=list,
        description="Stable long-document batch manifests without source text.",
    )
    max_provider_requests: int = Field(
        default=0,
        ge=0,
        description="Root Provider-call cap; zero preserves historical records without a cap.",
    )
    provider_requests_used: int = Field(
        default=0,
        ge=0,
        description="Atomically reserved root Provider calls, persisted before invocation.",
    )
    execution_budget_version: int = Field(
        default=0,
        ge=0,
        description="Optimistic version for atomic root execution-budget reservation.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp in UTC."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last state update timestamp in UTC."
    )
    review_gate2_result: ReviewGate2ResultV1 | None = Field(
        default=None,
        description="Completed deterministic Gate 2 audit; absent until automatic review is ready.",
    )
    review_gate2_route: NarrativeAnalysisReviewRouteV1 | None = Field(
        default=None,
        description="Safe downstream routing record derived from the Gate 2 result.",
    )
    recovery_outcomes: list[RecoveryOutcomeV1] = Field(
        default_factory=list,
        description="Append-only source-free summaries for Stage B recovery decisions.",
    )
    gate2_handoff: NarrativeGate2HandoffV1 | None = Field(
        default=None,
        description="Durable source-free checkpoint for deterministic Gate 2 completion.",
    )

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_run_version(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "schema_version" in value:
            updates: dict[str, Any] = {}
            if value.get("schema_version") in {"1.0", "1.1"} and "recovery_outcomes" not in value:
                updates["recovery_outcomes"] = []
            if value.get("schema_version") in {"1.0", "1.1", "1.2"} and "batches" not in value:
                updates["batches"] = []
            if (
                value.get("schema_version") in {"1.0", "1.1", "1.2", "1.3", "1.4"}
                and "gate2_handoff" not in value
            ):
                updates["gate2_handoff"] = None
            if updates:
                return {**value, **updates}
            return value
        return {
            **value,
            "schema_version": "1.0",
            "review_gate2_result": None,
            "review_gate2_route": None,
            "recovery_outcomes": [],
            "batches": [],
            "gate2_handoff": None,
        }

    @model_validator(mode="after")
    def validate_review_artifacts(self) -> "NarrativeAnalysisRunV1":
        if (self.review_gate2_result is None) != (self.review_gate2_route is None):
            raise ValueError("review_gate2_result and review_gate2_route must be present together")
        if self.schema_version == "1.0" and (
            self.review_gate2_result is not None or self.review_gate2_route is not None
        ):
            raise ValueError("v1.0 NarrativeAnalysisRun cannot contain Gate 2 artifacts")
        if self.review_gate2_result is not None and self.review_gate2_route is not None:
            result = self.review_gate2_result
            route = self.review_gate2_route
            if (
                result.analysis_run_id != self.analysis_run_id
                or route.analysis_run_id != self.analysis_run_id
            ):
                raise ValueError("Gate 2 artifact analysis_run_id must match the analysis run")
            if result.review_run_id != route.review_run_id or result.status != route.review_status:
                raise ValueError("Gate 2 route must match the stored review result")
        outcome_ids = [outcome.outcome_id for outcome in self.recovery_outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError("recovery_outcomes must have unique outcome ids")
        if any(
            outcome.root_analysis_run_id != self.analysis_run_id
            for outcome in self.recovery_outcomes
        ):
            raise ValueError("recovery outcome root_analysis_run_id must match the analysis run")
        return self


class NarrativeAnalysisCreateRequestV1(StrictBaseModel):
    """Chapter-scoped whole-document analysis request."""

    modes: list[str] = Field(
        default_factory=lambda: [
            "entity_extraction",
            "event_extraction",
            "claim_extraction",
            "knowledge_state_extraction",
            "state_change_extraction",
            "relationship_signal_extraction",
        ],
        min_length=1,
        description="Independent implemented NarrativeAnalyst modes.",
    )
    chapter_ids: list[str] | None = Field(
        default=None,
        description="Optional chapter selection; chunks are derived from approved Gate 1 output.",
    )
    document_revision: int | None = Field(
        default=None,
        ge=1,
        description="Optional source revision assertion.",
    )
    real_llm_requested: bool = Field(
        default=False,
        description="Explicit request-level opt-in; server settings remain authoritative.",
    )


class NarrativeAnalysisProposalSourceV1(StrictBaseModel):
    """One proposal with its source AgentRun for deterministic aggregation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    mode: str = Field(description="NarrativeAnalyst mode that produced the proposal.")
    agent_run_id: str = Field(description="Auditable AgentRun id.")
    proposal: (
        EventProposalV1
        | EntityProposalV1
        | ClaimProposalV1
        | KnowledgeStateProposalV1
        | StateChangeProposalV1
        | RelationshipSignalProposalV1
        | CampusContentProfileProposalV1
    ) = (
        Field(description="Typed proposal to aggregate.")
    )


class AggregatedEventProposalV1(StrictBaseModel):
    """Conservatively merged event candidate with audit references."""

    proposal: EventProposalV1 = Field(description="Representative event proposal.")
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedEntityProposalV1(StrictBaseModel):
    """Conservatively merged entity candidate with audit references."""

    proposal: EntityProposalV1 = Field(description="Representative entity proposal.")
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedClaimProposalV1(StrictBaseModel):
    """Conservatively merged claim candidate with audit references."""

    proposal: ClaimProposalV1 = Field(description="Representative claim proposal.")
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedKnowledgeStateProposalV1(StrictBaseModel):
    """Conservatively merged knowledge-state candidate with audit references."""

    proposal: KnowledgeStateProposalV1 = Field(
        description="Representative knowledge-state proposal."
    )
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedStateChangeProposalV1(StrictBaseModel):
    """Conservatively merged State Change candidate with audit references."""

    proposal: StateChangeProposalV1 = Field(
        description="Representative State Change proposal."
    )
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedRelationshipSignalProposalV1(StrictBaseModel):
    """Conservatively merged Relationship Signal candidate with audit references."""

    proposal: RelationshipSignalProposalV1 = Field(
        description="Representative relationship signal proposal."
    )
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class AggregatedCampusContentProfileProposalV1(StrictBaseModel):
    """Conservatively retained campus-content Profile candidate with audit references."""

    proposal: CampusContentProfileProposalV1
    agent_run_ids: list[str] = Field(min_length=1, description="Source AgentRun ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="All retained evidence.")


class NarrativeAnalysisResultV1(StrictBaseModel):
    """Typed, sanitized aggregate result for one whole-document task."""

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"] = Field(
        default="1.5", description="Schema version; v1.0-v1.4 results remain readable."
    )
    analysis_run_id: str = Field(description="Owning whole-document analysis run id.")
    events: list[AggregatedEventProposalV1] = Field(default_factory=list)
    entities: list[AggregatedEntityProposalV1] = Field(default_factory=list)
    claims: list[AggregatedClaimProposalV1] = Field(default_factory=list)
    knowledge_states: list[AggregatedKnowledgeStateProposalV1] = Field(default_factory=list)
    state_changes: list[AggregatedStateChangeProposalV1] = Field(default_factory=list)
    relationship_signals: list[AggregatedRelationshipSignalProposalV1] = Field(
        default_factory=list
    )
    campus_content_profiles: list["AggregatedCampusContentProfileProposalV1"] = Field(
        default_factory=list
    )

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_result_version(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "schema_version" in value:
            return value
        if (
            "knowledge_states" not in value
            and "state_changes" not in value
            and "relationship_signals" not in value
            and any(field in value for field in ("events", "entities", "claims"))
        ):
            return {
                **value,
                "schema_version": "1.0",
                "knowledge_states": [],
                "state_changes": [],
                "relationship_signals": [],
            }
        if "state_changes" not in value and "knowledge_states" in value:
            return {
                **value,
                "schema_version": "1.1",
                "state_changes": [],
                "relationship_signals": [],
            }
        if "relationship_signals" not in value:
            return {
                **value,
                "schema_version": "1.3",
                "relationship_signals": [],
                "campus_content_profiles": [],
            }
        if "campus_content_profiles" not in value:
            return {**value, "schema_version": "1.4", "campus_content_profiles": []}
        return {**value, "schema_version": "1.5"}


class AgentInputRefV1(StrictBaseModel):
    """Reference to one bounded object passed into an agent run."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    object_id: str = Field(description="Input object id, e.g. SourceChunk id.")
    object_schema: str = Field(description="Input object schema name.")
    role: str = Field(description="Input role in the agent context.")


class AgentOutputRefV1(StrictBaseModel):
    """Reference to one structured object produced by an agent run."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    object_id: str = Field(description="Output object id, e.g. Proposal id.")
    object_schema: str = Field(description="Output object schema name.")
    role: str = Field(description="Output role in the agent result.")


class ProviderResultV1(StrictBaseModel):
    """Auditable result from a provider call, including mock providers."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    provider_result_id: str = Field(description="Provider result id.")
    provider_name: str = Field(description="Provider adapter name.")
    provider_type: ProviderType = Field(description="Provider execution family.")
    model_name: str | None = Field(default=None, description="Optional model name.")
    output_schema: str = Field(description="Expected structured output schema.")
    raw_output: str | None = Field(default=None, description="Optional raw provider output.")
    structured_output: Any | None = Field(
        default=None,
        description="Optional parsed structured provider output.",
    )
    success: bool = Field(description="Whether the provider call succeeded.")
    error_message: str | None = Field(default=None, description="Failure message if any.")
    latency_ms: int | None = Field(default=None, ge=0, description="Optional latency in ms.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Created at.",
    )

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "ProviderResultV1":
        """Keep provider success/error state internally consistent."""

        if self.success:
            if self.error_message is not None:
                raise ValueError("successful provider results cannot include error_message")
            has_raw_output = self.raw_output not in (None, "")
            has_structured_output = self.structured_output is not None
            if not has_raw_output and not has_structured_output:
                raise ValueError("successful provider results require output")
        elif not self.error_message:
            raise ValueError("failed provider results require error_message")
        return self


class MockProviderResultV1(ProviderResultV1):
    """Provider result narrowed to deterministic mock provider output."""

    provider_name: str = Field(default="mock", description="Mock provider name.")
    provider_type: Literal[ProviderType.MOCK] = Field(
        default=ProviderType.MOCK,
        description="Mock provider family.",
    )


class AgentRunV1(StrictBaseModel):
    """One auditable agent execution over bounded source context."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    agent_run_id: str = Field(description="Agent run id.")
    project_id: str = Field(description="Project id.")
    agent_name: str = Field(description="Agent implementation name.")
    source_chunk_id: str | None = Field(default=None, description="Legacy single input chunk id.")
    agent_id: str | None = Field(default=None, description="Legacy agent implementation id.")
    output_proposal_id: str | None = Field(
        default=None,
        description="Legacy single output proposal id.",
    )
    workflow_run_id: str | None = Field(default=None, description="Legacy parent workflow id.")
    input_chunk_ids: list[str] = Field(
        default_factory=list,
        description="SourceChunk ids included in the agent context.",
    )
    output_proposal_ids: list[str] = Field(
        default_factory=list,
        description="Proposal ids produced by the agent.",
    )
    output_schema: str = Field(description="Primary output schema name.")
    provider_result_id: str | None = Field(default=None, description="Provider result id.")
    provider_result: ProviderResultV1 | None = Field(
        default=None,
        description="Inline provider result when not persisted separately.",
    )
    input_refs: list[AgentInputRefV1] = Field(
        default_factory=list,
        description="Structured input references.",
    )
    output_refs: list[AgentOutputRefV1] = Field(
        default_factory=list,
        description="Structured output references.",
    )
    status: AgentRunStatus = Field(description="Agent run status.")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Start timestamp.",
    )
    completed_at: datetime | None = Field(default=None, description="Completion timestamp.")
    error_message: str | None = Field(default=None, description="Failure message if any.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Additional audit payload.")

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_agent_run(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        source_chunk_id = value.get("source_chunk_id")
        agent_id = value.get("agent_id")
        output_proposal_id = value.get("output_proposal_id")
        return {
            **value,
            "agent_name": value.get("agent_name") or agent_id,
            "agent_id": agent_id or value.get("agent_name"),
            "input_chunk_ids": value.get("input_chunk_ids")
            or ([source_chunk_id] if source_chunk_id else []),
            "output_proposal_ids": value.get("output_proposal_ids")
            or ([output_proposal_id] if output_proposal_id else []),
            "output_schema": value.get("output_schema") or "EventProposalV1",
        }

    @property
    def created_at(self) -> datetime:
        """Expose the pre-v1 workflow timestamp used by the source repository."""

        return self.started_at

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "AgentRunV1":
        """Keep terminal agent run states auditable."""

        if self.status == AgentRunStatus.SUCCEEDED:
            if not self.input_chunk_ids:
                raise ValueError("succeeded agent runs require input_chunk_ids")
            has_output = bool(
                self.output_proposal_ids or self.provider_result_id or self.provider_result
            )
            if not has_output:
                raise ValueError(
                    "succeeded agent runs require output_proposal_ids or provider_result"
                )
            if self.error_message is not None:
                raise ValueError("succeeded agent runs cannot include error_message")
        elif self.status == AgentRunStatus.FAILED and not self.error_message:
            raise ValueError("failed agent runs require error_message")
        return self
