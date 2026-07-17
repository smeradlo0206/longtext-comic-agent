"""Health routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Return service health."""

    return {"status": "ok"}
