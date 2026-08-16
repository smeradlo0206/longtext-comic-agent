from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from anime_image_agent.scene_contracts import SceneJobV1, canonical_scene_bytes
from anime_image_agent.upstream_contracts import (
    MAPPING_AUDIT,
    UpstreamSceneEnvelopeV1,
    canonical_envelope_bytes,
    map_envelope_to_scene_job,
    schema_snapshot_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "upstream_scene_envelope.valid.json"


def load_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_envelope_strict_round_trip_and_schema_snapshot() -> None:
    envelope = UpstreamSceneEnvelopeV1.model_validate(load_payload())
    encoded = canonical_envelope_bytes(envelope)
    assert UpstreamSceneEnvelopeV1.model_validate_json(encoded) == envelope
    assert schema_snapshot_sha256() == (ROOT / "schemas" / "upstream-scene-envelope-v1.sha256").read_text().strip()

    payload = load_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UpstreamSceneEnvelopeV1.model_validate(payload)


def test_mapping_is_deterministic_and_documents_structural_loss() -> None:
    envelope = UpstreamSceneEnvelopeV1.model_validate(load_payload())
    first = map_envelope_to_scene_job(envelope)
    reparsed = SceneJobV1.model_validate(first.model_dump(mode="json"))
    second = map_envelope_to_scene_job(envelope)
    assert canonical_scene_bytes(first) == canonical_scene_bytes(reparsed) == canonical_scene_bytes(second)
    assert len(first.panels) == 3
    assert first.panels[2].dialogue[0].text == "有人来了。"
    assert any("char-a" in item for item in first.scene_context.continuity_notes)

    lost = {item.upstream_path for item in MAPPING_AUDIT.fields if item.disposition == "lost"}
    assert "event IDs and causal links" in lost
    assert "event state before/after and held-object changes" in lost
    assert "cross-panel movement direction" in lost


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["panels"][0]["event_ids"].append("missing-event"), "event reference is unknown"),
        (lambda p: p["panels"][1]["dialogue"][0].update({"speaker_id": "missing-character"}), "dialogue speaker is unknown"),
        (lambda p: p["events"][1]["cause_event_ids"].append("event-hide"), "must occur earlier"),
        (lambda p: p["events"][1]["state_changes"][0].update({"subject_id": "missing-object"}), "state subject is unknown"),
    ],
)
def test_bad_references_are_rejected(mutate, message: str) -> None:
    payload = load_payload()
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        UpstreamSceneEnvelopeV1.model_validate(payload)


def test_32_panel_boundary_and_overflow() -> None:
    payload = load_payload()
    template = payload["panels"][0]
    payload["panels"] = [
        {
            **template,
            "panel_id": f"panel-{index:03d}",
            "sequence_no": index,
        }
        for index in range(32)
    ]
    envelope = UpstreamSceneEnvelopeV1.model_validate(payload)
    assert len(map_envelope_to_scene_job(envelope).panels) == 32
    payload["panels"].append({**template, "panel_id": "panel-overflow", "sequence_no": 32})
    with pytest.raises(ValidationError, match="at most 32"):
        UpstreamSceneEnvelopeV1.model_validate(payload)
