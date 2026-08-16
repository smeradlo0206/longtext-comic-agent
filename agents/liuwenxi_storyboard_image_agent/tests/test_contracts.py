from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from anime_image_agent.contracts import (
    ImageJobV1,
    ImageResultV1,
    ResultStatus,
    seed_for_attempt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_valid_and_retry_examples_match_contract() -> None:
    for filename in ("image_job.valid.json", "image_job.retry.json"):
        job = ImageJobV1.model_validate_json(
            (ROOT / "examples" / filename).read_text(encoding="utf-8")
        )
        assert job.render_profile == "qwen-image-2512-landscape-v1"


def test_invalid_example_rejects_profile_and_unknown_override() -> None:
    with pytest.raises(ValidationError) as caught:
        ImageJobV1.model_validate_json(
            (ROOT / "examples" / "image_job.invalid.json").read_text(encoding="utf-8")
        )
    error_types = {error["type"] for error in caught.value.errors()}
    assert "literal_error" in error_types
    assert "extra_forbidden" in error_types


def test_unknown_nested_field_and_duplicate_characters_are_rejected() -> None:
    payload = json.loads((ROOT / "examples" / "image_job.valid.json").read_text(encoding="utf-8"))
    payload["panel_spec"]["unknown"] = True
    payload["panel_spec"]["character_ids"] = ["char-a", "char-a"]
    with pytest.raises(ValidationError) as caught:
        ImageJobV1.model_validate(payload)
    locations = {tuple(error["loc"]) for error in caught.value.errors()}
    assert ("panel_spec", "unknown") in locations
    assert ("panel_spec", "character_ids") in locations


def test_result_status_requires_matching_payload() -> None:
    with pytest.raises(ValidationError):
        ImageResultV1(
            request_id="request-1",
            project_id="project-1",
            chapter_id="chapter-1",
            scene_id="scene-1",
            panel_id="panel-1",
            sequence_no=1,
            status=ResultStatus.SUCCEEDED,
            attempts=1,
            completed_at="2026-08-11T12:00:00+08:00",
        )


def test_seed_is_deterministic_and_changes_by_attempt() -> None:
    assert seed_for_attempt("request-1", 1) == seed_for_attempt("request-1", 1)
    assert seed_for_attempt("request-1", 1) != seed_for_attempt("request-1", 2)


def test_committed_schemas_match_runtime_models() -> None:
    expected = {
        "image-job-v1.schema.json": ImageJobV1.model_json_schema(),
        "image-result-v1.schema.json": ImageResultV1.model_json_schema(),
    }
    for filename, schema in expected.items():
        committed = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert committed == schema
