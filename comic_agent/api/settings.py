"""Read-only settings routes for local development tools."""

from fastapi import APIRouter

from comic_agent.config import get_settings
from comic_agent.services.narrative_analyst_summary import implemented_mode_names

router = APIRouter()


@router.get("/settings/llm/status")
def get_llm_status() -> dict[str, object]:
    """Return sanitized LLM configuration status without exposing secrets."""

    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    return {
        "enable_real_llm": settings.enable_real_llm,
        "fake_pipeline_demo": settings.fake_pipeline_demo,
        "provider_name": settings.llm_provider_name,
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key_present": bool(api_key),
        "api_key_non_empty": bool(api_key),
        "real_pipeline_opt_in_available": bool(
            settings.enable_real_llm and api_key and not settings.fake_pipeline_demo
        ),
        "supported_modes": implemented_mode_names(),
    }
