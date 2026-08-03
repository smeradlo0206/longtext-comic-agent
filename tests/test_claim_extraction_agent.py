from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.claim_extraction import ClaimExtractionAgent
from comic_agent.schemas.narrative import ClaimProposalV1

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
        return output_model.model_validate(
            {
                "proposal_id": "claim-1",
                "claim_type": "ASSERTION",
                "claim_text": "The gate is sealed.",
                "source_type": "CHARACTER",
                "source_id": "char-demo",
                "target_event_id": None,
                "verification_status": "UNVERIFIED",
                "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "gate is sealed"}],
                "confidence": 0.82,
                "reality_layer": "PRIMARY",
            }
        )


def test_claim_extraction_agent_calls_provider_and_returns_claim_proposal() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)
    input_context = {
        "project_id": "project-1",
        "source_chunk_ids": ["chunk-1"],
        "source_chunks": [{"chunk_id": "chunk-1", "text": "She said the gate is sealed."}],
    }

    proposal = agent.run(input_context)

    assert isinstance(proposal, ClaimProposalV1)
    assert proposal.proposal_id == "claim-1"
    assert proposal.claim_type == "ASSERTION"
    assert proposal.verification_status == "UNVERIFIED"
    assert proposal.evidence_refs
    assert provider.output_models == [ClaimProposalV1]
    assert provider.requests[0]["input_context"] == input_context


def test_claim_extraction_agent_prompt_sets_claim_boundaries() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "She denied opening it."}],
        }
    )

    request = provider.requests[0]
    prompt = f"{request['system_prompt']}\n{request['user_prompt']}"
    for expected in [
        "exactly one",
        "ClaimProposalV1",
        "SourceChunk",
        "claim",
        "denial",
        "accusation",
        "prediction",
        "interpretation",
        "Do not output EventProposalV1",
        "Do not output EntityProposalV1",
        "StoryBible",
        "EvidenceRefV1",
        "quote_text",
        "UNVERIFIED",
        "reality_layer",
        "JSON only",
    ]:
        assert expected in prompt


def test_claim_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = ClaimExtractionAgent.spec

    assert spec.agent_id == "claim-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "ClaimProposalV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7
    assert spec.tools == []
