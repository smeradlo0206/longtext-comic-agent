"""Stable integration boundary for the anime generation pipeline."""

from .config import Settings
from .scene_contracts import SceneResultV1
from .upstream_contracts import UpstreamSceneEnvelopeV1

__all__ = [
    "UpstreamSceneEnvelopeV1",
    "SceneResultV1",
    "Settings",
]
