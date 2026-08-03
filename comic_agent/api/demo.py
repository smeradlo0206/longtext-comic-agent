"""Internal hosted demo routes and access-code checks."""

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header, HTTPException

from comic_agent.config import Settings, get_settings
from comic_agent.services.narrative_analyst_summary import implemented_mode_names

router = APIRouter()


@router.get("/demo/status")
def get_demo_status() -> dict[str, object]:
    """Return sanitized hosted demo runtime status."""

    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    return {
        "require_access_code": settings.internal_demo_require_access_code,
        "real_llm_enabled": settings.enable_real_llm,
        "provider_name": settings.llm_provider_name,
        "model": settings.llm_model,
        "api_key_configured": settings.llm_api_key is not None,
        "api_key_non_empty": bool(api_key),
        "supported_modes": ["mock", "real_event", *implemented_mode_names()],
    }


@router.post("/demo/verify-access")
def verify_demo_access(payload: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """Verify an internal demo access code without returning the configured code."""

    access_code = payload.get("access_code")
    require_demo_access_code(str(access_code) if access_code is not None else None)
    return {"access_granted": True}


def require_demo_access_code(
    x_demo_access_code: Annotated[str | None, Header(alias="X-Demo-Access-Code")] = None,
) -> None:
    """Authorize internal demo actions using a server-side access code."""

    settings = get_settings()
    if _access_allowed(settings, x_demo_access_code):
        return
    raise HTTPException(status_code=401, detail="Invalid demo access code")


def _access_allowed(settings: Settings, provided_code: str | None) -> bool:
    if not settings.internal_demo_require_access_code:
        return True
    expected = (
        settings.internal_demo_access_code.get_secret_value()
        if settings.internal_demo_access_code is not None
        else ""
    )
    if expected == "" or provided_code is None:
        return False
    return hmac.compare_digest(provided_code, expected)
