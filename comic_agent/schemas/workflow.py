"""Workflow run schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import StrictBaseModel


class AgentRunStatus(StrEnum):
    """Allowed lifecycle states for one agent execution."""

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
