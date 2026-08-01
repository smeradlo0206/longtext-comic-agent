from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.entity_extraction import EntityExtractionAgent
from comic_agent.schemas.narrative import EntityProposalV1

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
                "proposal_id": "entity-1",
                "entity_type": "CHARACTER",
                "canonical_name": "Lin Fan",
                "aliases": ["Young Master Lin"],
                "evidence_refs": [
                    {
                        "chunk_id": "chunk-1",
                        "quote_text": "Young Master Lin",
                    }
                ],
                "confidence": 0.9,
            }
        )


def test_entity_extraction_agent_calls_provider_and_returns_entity_proposal() -> None:
    provider = FakeProvider()
    agent = EntityExtractionAgent(provider)

    proposal = agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [
                {
                    "chunk_id": "chunk-1",
                    "text": "Young Master Lin stepped into the hall.",
                }
            ],
        }
    )

    assert isinstance(proposal, EntityProposalV1)
    assert proposal.proposal_id == "entity-1"
    assert proposal.canonical_name == "Lin Fan"
    assert proposal.evidence_refs
    assert provider.requests
    assert provider.requests[0]["input_context"]["source_chunk_ids"] == ["chunk-1"]  # type: ignore[index]


def test_entity_extraction_agent_prompt_sets_entity_boundaries() -> None:
    provider = FakeProvider()
    agent = EntityExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "Young Master Lin."}],
        }
    )

    request = provider.requests[0]
    prompt = f"{request['system_prompt']}\n{request['user_prompt']}"
    for expected in [
        "exactly one",
        "EntityProposalV1",
        "source_chunks",
        "Do not invent",
        "canonical_name",
        "aliases",
        "quote_text",
        "EvidenceRef",
        "JSON only",
        "StoryBible",
    ]:
        assert expected in prompt


def test_entity_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = EntityExtractionAgent.spec

    assert spec.agent_id == "entity-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "EntityProposalV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7
    assert spec.tools == []


def test_entity_extraction_agent_prompt_excludes_other_proposal_outputs() -> None:
    provider = FakeProvider()
    agent = EntityExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "Young Master Lin."}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for forbidden_output in [
        "EventProposalV1",
        "ClaimProposalV1",
        "KnowledgeStateProposalV1",
        "canonical StoryBible data",
    ]:
        assert forbidden_output in prompt
