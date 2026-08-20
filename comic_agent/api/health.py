"""Health routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return service health."""

    return {"status": "ok"}


@router.get("/demo/status")
def demo_status() -> dict[str, str]:
    """Keep the local Console's legacy readiness probe source-free and non-misleading."""

    return {"status": "available"}
