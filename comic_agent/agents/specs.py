"""Agent contract schemas."""

from typing import Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class AgentSpec(StrictBaseModel):
    """Static contract for an agent implementation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    agent_id: str = Field(description="Agent identifier.")
    version: str = Field(description="Agent implementation version.")
    reads: list[str] = Field(default_factory=list, description="Schema names this agent reads.")
    output_schema: str = Field(description="Schema name this agent outputs.")
    tools: list[str] = Field(default_factory=list, description="Allowed tool names.")
    can_write_canonical_data: bool = Field(
        default=False,
        description="Agents must not write canonical story data.",
    )
    requires_evidence: bool = Field(
        default=True,
        description="Whether output requires EvidenceRef.",
    )
    max_context_chunks: int = Field(default=20, ge=1, description="Maximum source chunks per run.")
    confidence_threshold: float = Field(default=0.7, ge=0, le=1, description="Minimum confidence.")
