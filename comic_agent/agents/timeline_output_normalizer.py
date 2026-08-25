"""Conservative pre-validation normalization for Timeline pair output."""

import re

TIMELINE_PAIR_OUTPUT_NORMALIZER = "TIMELINE_PAIR_V1"

_RELATION_ALIASES = {
    "before": "BEFORE",
    "before_event": "BEFORE",
    "after": "AFTER",
}
_DECIMAL_CONFIDENCE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_PERCENT_CONFIDENCE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%$")


def normalize_timeline_pair_output(payload: dict[str, object]) -> dict[str, object]:
    """Return a copied payload with only unambiguous presentation variants fixed.

    This function deliberately does not invent evidence, event identifiers, or
    relation semantics.  Unsupported values are returned unchanged so the
    authoritative Pydantic contract remains responsible for rejecting them.
    """

    normalized = dict(payload)
    _move_alias(normalized, alias="time_relation", field="relation")
    _move_alias(normalized, alias="score", field="confidence")
    _normalize_relation(normalized)
    _normalize_confidence(normalized)
    return normalized


def _move_alias(payload: dict[str, object], *, alias: str, field: str) -> None:
    """Move an alias only when it cannot conflict with a canonical field."""

    if alias in payload and field not in payload:
        payload[field] = payload.pop(alias)


def _normalize_relation(payload: dict[str, object]) -> None:
    value = payload.get("relation")
    if not isinstance(value, str):
        return
    normalized = _RELATION_ALIASES.get(value.strip().casefold())
    if normalized is not None:
        payload["relation"] = normalized


def _normalize_confidence(payload: dict[str, object]) -> None:
    value = payload.get("confidence")
    if not isinstance(value, str):
        return
    candidate = value.strip()
    if _PERCENT_CONFIDENCE.fullmatch(candidate):
        payload["confidence"] = float(candidate[:-1]) / 100
    elif _DECIMAL_CONFIDENCE.fullmatch(candidate):
        payload["confidence"] = float(candidate)
