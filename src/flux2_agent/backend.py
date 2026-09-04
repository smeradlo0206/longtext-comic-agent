"""Compatibility exports for the canonical local image Provider."""

from comic_agent.providers.flux2_local import (
    Flux2Backend,
    LocalFlux2ImageProvider,
    load_reference,
)

__all__ = ["Flux2Backend", "LocalFlux2ImageProvider", "load_reference"]
