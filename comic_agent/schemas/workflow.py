"""Workflow run schemas."""

from datetime import UTC, datetime
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
