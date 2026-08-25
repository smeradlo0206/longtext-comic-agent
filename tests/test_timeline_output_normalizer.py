"""Safety boundaries for Timeline pair-output normalization."""

import pytest
from pydantic import ValidationError

from comic_agent.agents.timeline_output_normalizer import normalize_timeline_pair_output
from comic_agent.schemas.timeline import TimelinePairInferenceV1


@pytest.mark.parametrize(
    ("payload", "expected_relation", "expected_confidence"),
    [
        (
            {"relation": "Before", "evidence_indexes": [0], "confidence": "0.8"},
            "BEFORE",
            0.8,
        ),
        (
            {"relation": "before_event", "evidence_indexes": [0], "confidence": "90%"},
            "BEFORE",
            0.9,
        ),
        (
            {"time_relation": "after", "evidence_indexes": [0], "score": "0.9"},
            "AFTER",
            0.9,
        ),
    ],
)
def test_normalizer_converts_only_supported_timeline_pair_format_variants(
    payload: dict[str, object], expected_relation: str, expected_confidence: float
) -> None:
    normalized = normalize_timeline_pair_output(payload)

    validated = TimelinePairInferenceV1.model_validate(normalized)

    assert validated.relation == expected_relation
    assert validated.confidence == expected_confidence


@pytest.mark.parametrize(
    "payload",
    [
        {"relation": "earlier", "evidence_indexes": [0], "confidence": 0.9},
        {"relation": "BEFORE", "evidence_indexes": [0], "confidence": "120%"},
        # Pair inference intentionally has no event IDs.  It must nevertheless
        # reject a known relation with no selected source evidence.
        {"relation": "BEFORE", "evidence_indexes": [], "confidence": 0.9},
    ],
)
def test_normalizer_leaves_unsafe_or_incomplete_pair_output_for_schema_rejection(
    payload: dict[str, object],
) -> None:
    normalized = normalize_timeline_pair_output(payload)

    with pytest.raises(ValidationError):
        TimelinePairInferenceV1.model_validate(normalized)
