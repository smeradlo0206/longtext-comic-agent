"""Continuity and state schemas."""

from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import RealityLayer, StrictBaseModel


class CharacterStateV1(StrictBaseModel):
    """Compiled character state over a story-time interval."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    state_id: str = Field(description="Character state id.")
    character_id: str = Field(description="Character entity id.")
    valid_from_event_id: str | None = Field(default=None, description="Start event id.")
    valid_until_event_id: str | None = Field(default=None, description="End event id.")
    reality_layer: RealityLayer = Field(description="Narrative reality layer.")
    appearance: dict[str, Any] = Field(default_factory=dict, description="Appearance facts.")
    physical_state: dict[str, Any] = Field(default_factory=dict, description="Body state facts.")
    inventory_ids: list[str] = Field(default_factory=list, description="Held prop ids.")
    knowledge_fact_ids: list[str] = Field(default_factory=list, description="Known fact ids.")
