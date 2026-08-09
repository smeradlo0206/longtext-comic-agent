"""Workflow run schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, StrictBaseModel
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
)


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
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
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

    schema_version: Literal["1.0", "1.1", "1.2"] = Field(
        default="1.2",
        description="Schema version. Versions 1.0 and 1.1 records remain readable.",
    )
    window_index: int = Field(ge=0, description="Zero-based window sequence.")
    chunk_ids: list[str] = Field(min_length=1, description="Ordered source chunk ids.")


class NarrativeAnalysisWindowV1(NarrativeAnalysisWindowPlanV1):
    """Auditable state for one mode over one planned source window."""

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


class NarrativeAnalysisRunV1(StrictBaseModel):
    """Persistent, resumable whole-document NarrativeAnalyst task."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp in UTC."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last state update timestamp in UTC."
    )


class NarrativeAnalysisCreateRequestV1(StrictBaseModel):
    """Normal whole-document analysis request without manual chunk selection."""

    modes: list[str] = Field(min_length=1, description="Independent NarrativeAnalyst modes.")
    real_llm_requested: bool = Field(
        default=False,
        description="Explicit request-level opt-in; server settings remain authoritative.",
    )


class NarrativeAnalysisProposalSourceV1(StrictBaseModel):
    """One proposal with its source AgentRun for deterministic aggregation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    mode: str = Field(description="NarrativeAnalyst mode that produced the proposal.")
    agent_run_id: str = Field(description="Auditable AgentRun id.")
    proposal: EventProposalV1 | EntityProposalV1 | ClaimProposalV1 = Field(
        description="Typed proposal to aggregate."
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


class NarrativeAnalysisResultV1(StrictBaseModel):
    """Typed, sanitized aggregate result for one whole-document task."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    analysis_run_id: str = Field(description="Owning whole-document analysis run id.")
    events: list[AggregatedEventProposalV1] = Field(default_factory=list)
    entities: list[AggregatedEntityProposalV1] = Field(default_factory=list)
    claims: list[AggregatedClaimProposalV1] = Field(default_factory=list)


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
