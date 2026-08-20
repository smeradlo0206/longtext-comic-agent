"""Unit coverage for the opt-in local real Provider acceptance runner."""

import pytest
from pydantic import SecretStr

from comic_agent.config import Settings
from comic_agent.schemas.reliability import StructuredOutputPolicy
from scripts.run_local_real_provider_acceptance import acceptance_text, validate_live_settings


def test_acceptance_text_tiers_increase_scope_without_user_source() -> None:
    assert len(acceptance_text("short")) < len(acceptance_text("medium"))
    assert len(acceptance_text("medium")) < len(acceptance_text("long"))
    assert "林岚" in acceptance_text("short")


def test_runner_refuses_real_execution_without_safe_local_opt_in() -> None:
    settings = Settings(
        _env_file=None,
        comic_agent_env="development",
        enable_real_llm=True,
        fake_pipeline_demo=False,
        llm_api_key=SecretStr("local-only"),
        llm_structured_output_policy=StructuredOutputPolicy.JSON_OBJECT_ONLY,
    )

    with pytest.raises(ValueError, match="LLM_STRUCTURED_OUTPUT_POLICY"):
        validate_live_settings(settings)


def test_runner_accepts_explicit_development_configuration() -> None:
    settings = Settings(
        _env_file=None,
        comic_agent_env="development",
        enable_real_llm=True,
        fake_pipeline_demo=False,
        llm_api_key=SecretStr("local-only"),
        llm_structured_output_policy=StructuredOutputPolicy.AUTO,
    )

    validate_live_settings(settings)
