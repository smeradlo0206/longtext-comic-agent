"""Stable id helpers."""

from hashlib import sha256


def stable_id(prefix: str, *parts: object) -> str:
    """Return a deterministic id for idempotent imports."""

    payload = "\x1f".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def checksum_text(text: str) -> str:
    """Return a SHA-256 checksum for UTF-8 text."""

    return sha256(text.encode("utf-8")).hexdigest()


def checksum_bytes(data: bytes) -> str:
    """Return a SHA-256 checksum for raw bytes."""

    return sha256(data).hexdigest()
