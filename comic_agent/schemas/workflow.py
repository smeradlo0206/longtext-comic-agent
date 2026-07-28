"""Workflow run schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


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


class AgentRunStatus(StrEnum):
    """Lifecycle outcome of one agent execution."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AgentRunV1(StrictBaseModel):
    """Trace record for one agent execution against one source chunk."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    agent_run_id: str = Field(description="Unique agent run id.")
    project_id: str = Field(description="Project owning the input chunk.")
    source_chunk_id: str = Field(description="Source chunk supplied to the agent.")
    agent_id: str = Field(description="Agent implementation identifier.")
    status: AgentRunStatus = Field(description="Execution outcome.")
    output_proposal_id: str | None = Field(
        default=None,
        description="Proposal produced by a successful run, if any.",
    )
    error_message: str | None = Field(default=None, description="Error for a failed run, if any.")
    workflow_run_id: str | None = Field(default=None, description="Optional parent workflow run.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp in UTC.",
    )
