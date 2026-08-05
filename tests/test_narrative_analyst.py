from typing import TypeVar

import pytest
from pydantic import BaseModel

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalBatchV1,
)

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
                            "evidence_refs": [
                                {"chunk_id": "chunk-1", "quote_text": "door opened"}
                            ],
                            "confidence": 0.86,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )
        if output_model is EntityProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "entity-1",
                    "entity_type": "CHARACTER",
                    "canonical_name": "Demo Entity",
                    "aliases": [],
                    "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "Demo Entity"}],
                    "confidence": 0.88,
                }
            )
        if output_model is ClaimProposalV1:
            return output_model.model_validate(
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

    proposal = analyst.run("entity_extraction", _input_context())

    assert isinstance(proposal, EntityProposalV1)
    assert proposal.proposal_id == "entity-1"
    assert provider.output_models == [EntityProposalV1]
    assert provider.requests[0]["input_context"] == _input_context()


def test_narrative_analyst_routes_claim_extraction_to_existing_agent() -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    proposal = analyst.run("claim_extraction", _input_context())

    assert isinstance(proposal, ClaimProposalV1)
    assert proposal.proposal_id == "claim-1"
    assert proposal.evidence_refs
    assert provider.output_models == [ClaimProposalV1]
    assert provider.requests[0]["input_context"] == _input_context()


@pytest.mark.parametrize(
    ("mode", "output_schema", "schema_class"),
    [
        ("event_extraction", "EventProposalBatchV1", EventProposalBatchV1),
        ("entity_extraction", "EntityProposalV1", EntityProposalV1),
        ("claim_extraction", "ClaimProposalV1", ClaimProposalV1),
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


@pytest.mark.parametrize(
    ("mode", "output_schema"),
    [
        ("knowledge_state_extraction", "KnowledgeStateProposalV1"),
        ("state_change_extraction", "StateChangeProposalV1"),
    ],
)
def test_planned_mode_is_registered_but_not_implemented_and_does_not_call_provider(
    mode: str,
    output_schema: str,
) -> None:
    provider = FakeProvider()
    analyst = NarrativeAnalyst(provider)

    spec = analyst.get_mode_spec(mode)
    with pytest.raises(NotImplementedError) as exc_info:
        analyst.run(mode, _input_context())

    message = str(exc_info.value)
    assert spec.status == "planned"
    assert spec.output_schema == output_schema
    assert provider.requests == []
    assert mode in message
    assert "planned" in message
    assert "secret-test-source" not in message
    assert "secret-test-key" not in message
    assert "raw provider" not in message
    assert "message.content" not in message


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
