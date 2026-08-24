from typing import TypeVar

import pytest
from pydantic import BaseModel

from comic_agent.agents.event_extraction import EVENT_EXTRACTION_SYSTEM_PROMPT
from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    EntityProposalBatchV1,
    EventProposalBatchV1,
    KnowledgeStateProposalBatchV1,
    RelationshipSignalProposalBatchV1,
    StateChangeProposalBatchV1,
)
from comic_agent.schemas.source import SourceChunkV1

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.output_models: list[type[BaseModel]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.requests.append(request)
        self.output_models.append(output_model)
        if output_model is EventProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "event-batch-1",
                    "events": [
                        {
                            "proposal_id": "event-1",
                            "event_type": "handoff",
                            "summary": "A concise supported event.",
                            "participant_ids": [],
                            "actor_resolution_status": "UNKNOWN",
                            "location_id": None,
                            "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "door opened"}],
                            "confidence": 0.86,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )
        if output_model is EntityProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "entity-batch-1",
                    "entities": [
                        {
                            "proposal_id": "entity-1",
                            "entity_type": "CHARACTER",
                            "canonical_name": "Demo Entity",
                            "aliases": [],
                            "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "Demo Entity"}],
                            "confidence": 0.88,
                        }
                    ],
                }
            )
        if output_model is ClaimProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "claim-batch-1",
                    "claims": [
                        {
                            "proposal_id": "claim-1",
                            "claim_type": "DENIAL",
                            "claim_text": "The narrator denies the rumor.",
                            "source_type": "NARRATOR",
                            "source_id": None,
                            "target_event_id": None,
                            "verification_status": "UNVERIFIED",
                            "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "denies"}],
                            "confidence": 0.79,
                            "reality_layer": "PRIMARY",
                            "temporal_scope": "PRESENT",
                        }
                    ],
                }
            )
        if output_model is StateChangeProposalBatchV1:
            return output_model.model_validate(
                {
                    "schema_version": "1.2",
                    "batch_id": "state-change-batch-1",
                    "changes": [],
                }
            )
        if output_model is RelationshipSignalProposalBatchV1:
            return output_model.model_validate(
                {
                    "schema_version": "1.0",
                    "batch_id": "relationship-signal-batch-1",
                    "signals": [],
                }
            )
        raise AssertionError(f"Unexpected output model: {output_model}")


def _input_context() -> dict[str, object]:
    return {
        "project_id": "project-1",
        "source_chunk_ids": ["chunk-1"],
        "source_chunks": [{"chunk_id": "chunk-1", "text": "secret-test-source text"}],
        "api_key_hint": "secret-test-key",
    }


def _state_change_input_context() -> dict[str, object]:
    source_chunk = SourceChunkV1(
        chunk_id="chunk-1",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text="secret-test-source text",
        checksum="fixture-only",
    )
    return _input_context() | {
        "source_chunks": [source_chunk.model_dump(mode="json")],
    }


def test_narrative_analyst_list_modes_includes_event_and_entity() -> None:
    analyst = NarrativeAnalyst(FakeProvider())

    mode_names = [mode.mode for mode in analyst.list_modes()]

    assert "event_extraction" in mode_names
    assert "entity_extraction" in mode_names
    assert "claim_extraction" in mode_names


def test_narrative_analyst_routes_event_extraction_to_existing_agent() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    batch = analyst.run("event_extraction", _input_context())

    assert isinstance(batch, EventProposalBatchV1)
    assert batch.events[0].proposal_id == "event-1"
    assert provider.output_models == [EventProposalBatchV1]
    assert provider.requests[0]["input_context"] == _input_context()


def test_narrative_analyst_routes_entity_extraction_to_existing_agent() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    batch = analyst.run("entity_extraction", _input_context())

    assert isinstance(batch, EntityProposalBatchV1)
    assert batch.entities[0].proposal_id == "entity-1"
    assert provider.output_models == [EntityProposalBatchV1]
    assert provider.requests[0]["input_context"] == _input_context()


def test_narrative_analyst_routes_claim_extraction_to_existing_agent() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    batch = analyst.run("claim_extraction", _input_context())

    assert isinstance(batch, ClaimProposalBatchV1)
    assert batch.claims[0].proposal_id == "claim-1"
    assert batch.claims[0].evidence_refs
    assert provider.output_models == [ClaimProposalBatchV1]
    assert provider.requests[0]["input_context"] == _input_context()


@pytest.mark.parametrize(
    ("mode", "output_schema", "schema_class"),
    [
        ("event_extraction", "EventProposalBatchV1", EventProposalBatchV1),
        ("entity_extraction", "EntityProposalBatchV1", EntityProposalBatchV1),
        ("claim_extraction", "ClaimProposalBatchV1", ClaimProposalBatchV1),
        (
            "knowledge_state_extraction",
            "KnowledgeStateProposalBatchV1",
            KnowledgeStateProposalBatchV1,
        ),
        (
            "state_change_extraction",
            "StateChangeProposalBatchV1",
            StateChangeProposalBatchV1,
        ),
        (
            "relationship_signal_extraction",
            "RelationshipSignalProposalBatchV1",
            RelationshipSignalProposalBatchV1,
        ),
    ],
)
def test_implemented_mode_specs_are_bounded_evidence_required_and_proposal_only(
    mode: str,
    output_schema: str,
    schema_class: type[BaseModel],
) -> None:
    analyst = NarrativeAnalyst(FakeProvider())

    spec = analyst.get_mode_spec(mode)

    assert spec.mode == mode
    assert spec.status == "implemented"
    assert spec.output_schema == output_schema
    assert spec.schema_class is schema_class
    assert spec.max_context_chunks == 3
    assert spec.requires_evidence is True
    assert spec.proposal_only is True


def test_state_change_extraction_routes_to_agent_and_accepts_empty_batch() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    input_context = _state_change_input_context()
    batch = analyst.run("state_change_extraction", input_context)

    assert isinstance(batch, StateChangeProposalBatchV1)
    assert batch.schema_version == "1.2"
    assert batch.changes == []
    assert provider.output_models == [StateChangeProposalBatchV1]
    assert provider.requests[0]["input_context"] == input_context


def test_relationship_signal_extraction_routes_to_agent_and_accepts_empty_batch() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    input_context = _state_change_input_context()
    batch = analyst.run("relationship_signal_extraction", input_context)

    assert isinstance(batch, RelationshipSignalProposalBatchV1)
    assert batch.schema_version == "1.0"
    assert batch.signals == []
    assert provider.output_models == [RelationshipSignalProposalBatchV1]
    assert provider.requests[0]["input_context"] == input_context


def test_unknown_mode_is_rejected_and_does_not_call_provider() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    with pytest.raises(ValueError) as exc_info:
        analyst.run("unknown_mode", _input_context())

    message = str(exc_info.value)
    assert provider.requests == []
    assert message == "Unsupported NarrativeAnalyst mode: unknown_mode"
    assert "secret-test-source" not in message
    assert "secret-test-key" not in message
    assert "raw provider" not in message
    assert "message.content" not in message


def test_event_extraction_prompt_matches_actor_resolution_validator_contract() -> None:
    prompt = EVENT_EXTRACTION_SYSTEM_PROMPT

    for token in (
        "KNOWN",
        "UNKNOWN",
        "UNRESOLVED",
        "NOT_APPLICABLE",
        "UNSPECIFIED",
        "participant_ids",
        "unresolved_actor_ref_id",
    ):
        assert token in prompt
    assert "KNOWN: include at least one participant_ids OR participant_mentions value" in prompt
    assert "UNKNOWN: participant_ids and participant_mentions MUST both be empty" in prompt
    assert "UNRESOLVED: participant_ids and participant_mentions MUST both be empty" in prompt
    assert "unresolved_actor_ref_id MUST be a non-null ID already supplied" in prompt
    assert "participant_mentions may be present or may both be empty" in prompt
    assert (
        "Never invent EntityProposal ids, location ids, or unresolved_actor_ref_id values."
        in prompt
    )
