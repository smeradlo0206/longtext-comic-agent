from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.event_extraction import EventExtractionAgent
from comic_agent.schemas.narrative import EventProposalV1

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.requests.append(request)
        return output_model.model_validate(
            {
                "proposal_id": "proposal-1",
                "event_type": "handoff",
                "summary": "陈野把伞递给林夏。",
                "participant_ids": ["char-chen", "char-lin"],
                "actor_resolution_status": "KNOWN",
                "location_id": None,
                "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "伞递给"}],
                "confidence": 0.91,
                "reality_layer": "PRIMARY",
            }
        )


def test_event_extraction_agent_calls_provider_and_returns_event_proposal() -> None:
    provider = FakeProvider()
    agent = EventExtractionAgent(provider)

    proposal = agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "陈野把伞递给林夏。"}],
        }
    )

    assert isinstance(proposal, EventProposalV1)
    assert proposal.proposal_id == "proposal-1"
    assert provider.requests
    assert provider.requests[0]["input_context"]["source_chunk_ids"] == ["chunk-1"]  # type: ignore[index]


def test_event_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = EventExtractionAgent.spec

    assert spec.agent_id == "event-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "EventProposalV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7
