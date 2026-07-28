import pytest
from pydantic import ValidationError

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)


def event_payload() -> dict[str, object]:
    return {
        "proposal_id": "proposal-event-1",
        "event_type": "handoff",
        "summary": "陈野把伞递给林夏。",
        "participant_ids": ["char-chen", "char-lin"],
        "location_id": "loc-playground",
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1")],
        "confidence": 0.9,
        "reality_layer": RealityLayer.PRIMARY,
    }


def test_event_proposal_minimal_valid_example() -> None:
    event = EventProposalV1(**event_payload())

    assert event.proposal_id == "proposal-event-1"
    assert event.evidence_refs[0].chunk_id == "chunk-1"
    assert event.confidence == 0.9


def test_event_proposal_requires_evidence_refs() -> None:
    payload = event_payload()
    payload.pop("evidence_refs")

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_event_proposal_rejects_empty_evidence_refs() -> None:
    payload = event_payload() | {"evidence_refs": []}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_event_proposal_rejects_confidence_out_of_bounds(confidence: float) -> None:
    payload = event_payload() | {"confidence": confidence}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_event_proposal_rejects_extra_fields() -> None:
    payload = event_payload() | {"canonical_event_id": "event-1"}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_temporal_relation_known_relation_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="BEFORE",
            confidence=0.8,
        )


def test_temporal_relation_unknown_rejects_offset() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="UNKNOWN",
            offset_value=3,
            offset_unit="days",
            confidence=0.5,
        )


def test_temporal_relation_rejects_self_loop() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-1",
            relation="SIMULTANEOUS",
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
            confidence=0.8,
        )


def test_state_change_proposal_minimal_valid_example() -> None:
    state_change = StateChangeProposalV1(
        proposal_id="proposal-state-1",
        event_id="event-1",
        target_entity_id="char-lin",
        attribute_path="appearance.hair",
        old_value=None,
        new_value="short",
        persistent=True,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
        confidence=0.87,
    )

    assert state_change.target_entity_id == "char-lin"
    assert state_change.evidence_refs[0].chunk_id == "chunk-1"
