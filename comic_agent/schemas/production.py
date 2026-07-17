"""Production schemas reserved for provider-specific prompt compilation."""

from typing import Any, Literal

from pydantic import Field

from comic_agent.schemas.base import StrictBaseModel


class PromptSpecV1(StrictBaseModel):
    """Provider-facing prompt payload produced after PanelSpec validation."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    prompt_id: str = Field(description="Prompt id.")
    panel_id: str = Field(description="Panel id.")
    provider: str = Field(description="Image provider name.")
    model_name: str | None = Field(default=None, description="Optional provider model name.")
    provider_prompt: str = Field(description="Compiled provider prompt text.")
    provider_options: dict[str, Any] = Field(default_factory=dict, description="Provider options.")
