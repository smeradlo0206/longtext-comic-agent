import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.agents.event_extraction import (
    EVENT_EXTRACTION_SYSTEM_PROMPT,
    EventExtractionAgent,
)
from comic_agent.schemas.narrative import EventProposalBatchV1


class _FakeStructuredProvider:
    """Local provider double that validates exactly as the provider boundary does."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[BaseModel],
    ) -> BaseModel:
        self.requests.append(request)
        return output_model.model_validate(self.payload)


def _event_batch(
    *,
    actor_resolution_status: str,
    participant_ids: list[str] | None = None,
    participant_mentions: list[dict[str, object]] | None = None,
    unresolved_actor_ref_id: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "batch_id": "event-batch-1",
        "events": [
            {
                "schema_version": "1.1",
                "proposal_id": "event-1",
                "event_type": "ACTION",
                "summary": "A bounded action occurs.",
                "participant_ids": participant_ids or [],
                "participant_mentions": participant_mentions or [],
                "actor_resolution_status": actor_resolution_status,
                "unresolved_actor_ref_id": unresolved_actor_ref_id,
                "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "An action occurs."}],
                "confidence": 0.8,
                "reality_layer": "PRIMARY",
            }
        ],
    }


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (
            _event_batch(
                actor_resolution_status="KNOWN",
                participant_mentions=[
                    {
                        "mention_text": "source actor",
                        "resolution_status": "UNRESOLVED",
                    }
                ],
            ),
            "KNOWN",
        ),
        (_event_batch(actor_resolution_status="KNOWN", participant_ids=["entity-1"]), "KNOWN"),
        (
            _event_batch(
                actor_resolution_status="UNRESOLVED",
                unresolved_actor_ref_id="unresolved-actor-1",
            ),
            "UNRESOLVED",
        ),
    ],
)
def test_event_extraction_accepts_schema_valid_actor_combinations(
    payload: dict[str, object], expected_status: str
) -> None:
    provider = _FakeStructuredProvider(payload)

    result = EventExtractionAgent(provider).run(
        {"project_id": "project-1", "source_chunk_ids": ["chunk-1"], "source_chunks": []}
    )

    assert isinstance(result, EventProposalBatchV1)
    assert result.events[0].actor_resolution_status == expected_status
    assert provider.requests[0]["system_prompt"] == EVENT_EXTRACTION_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "payload",
    [
        _event_batch(actor_resolution_status="KNOWN"),
        _event_batch(
            actor_resolution_status="UNRESOLVED",
            participant_mentions=[
                {
                    "mention_text": "source actor",
                    "resolution_status": "UNRESOLVED",
                }
            ],
            unresolved_actor_ref_id="unresolved-actor-1",
        ),
    ],
)
def test_event_extraction_rejects_invalid_actor_combinations(payload: dict[str, object]) -> None:
    provider = _FakeStructuredProvider(payload)

    with pytest.raises(ValidationError):
        EventExtractionAgent(provider).run(
            {"project_id": "project-1", "source_chunk_ids": ["chunk-1"], "source_chunks": []}
        )


def test_event_prompt_matches_known_and_unresolved_actor_schema_rules() -> None:
    assert "participant_ids OR participant_mentions" in EVENT_EXTRACTION_SYSTEM_PROMPT
    assert "KNOWN: participant_ids MUST contain at least one resolved entity ID" not in (
        EVENT_EXTRACTION_SYSTEM_PROMPT
    )
    assert "UNRESOLVED: participant_ids and participant_mentions MUST both be empty" in (
        EVENT_EXTRACTION_SYSTEM_PROMPT
    )
    assert "Never invent EntityProposal ids, location ids, or unresolved_actor_ref_id values." in (
        EVENT_EXTRACTION_SYSTEM_PROMPT
    )
