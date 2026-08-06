from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.claim_extraction import ClaimExtractionAgent
from comic_agent.schemas.narrative import ClaimProposalBatchV1, ClaimTemporalScope, ClaimType

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
                "batch_id": "claim-batch-1",
                "claims": [
                    {
                        "proposal_id": "claim-1",
                        "claim_type": "FACTUAL_ASSERTION",
                        "claim_text": "The gate is sealed.",
                        "source_type": "CHARACTER",
                        "source_id": "char-demo",
                        "target_event_id": None,
                        "verification_status": "UNVERIFIED",
                        "evidence_refs": [
                            {"chunk_id": "chunk-1", "quote_text": "gate is sealed"}
                        ],
                        "confidence": 0.82,
                        "reality_layer": "PRIMARY",
                        "temporal_scope": "PRESENT",
                    },
                    {
                        "proposal_id": "claim-2",
                        "claim_type": "COMMITMENT",
                        "claim_text": "I will seal the gate.",
                        "source_type": "CHARACTER",
                        "source_id": "char-demo",
                        "target_event_id": None,
                        "verification_status": "UNVERIFIED",
                        "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "I will"}],
                        "confidence": 0.74,
                        "reality_layer": "PRIMARY",
                        "temporal_scope": "FUTURE",
                    },
                ],
            }
        )


def test_claim_extraction_agent_calls_provider_and_returns_claim_batch() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)
    input_context = {
        "project_id": "project-1",
        "source_chunk_ids": ["chunk-1"],
        "source_chunks": [{"chunk_id": "chunk-1", "text": "She said the gate is sealed."}],
    }

    batch = agent.run(input_context)

    assert isinstance(batch, ClaimProposalBatchV1)
    assert batch.schema_version == "1.2"
    assert batch.batch_id == "claim-batch-1"
    assert [claim.proposal_id for claim in batch.claims] == ["claim-1", "claim-2"]
    assert batch.claims[0].claim_type == ClaimType.FACTUAL_ASSERTION
    assert batch.claims[0].temporal_scope == ClaimTemporalScope.PRESENT
    assert batch.claims[1].claim_type == ClaimType.COMMITMENT
    assert batch.claims[0].verification_status == "UNVERIFIED"
    assert provider.output_models == [ClaimProposalBatchV1]
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
        "ClaimProposalBatchV1",
        "schema_version=\"1.2\"",
        "claims",
        "number of claims must be based on real claims, not chunk count",
        "multiple claims",
        "same claim appears across chunks, output it once",
        "ClaimProposalV1",
        "SourceChunk",
        "claim",
        "FACTUAL_ASSERTION",
        "BELIEF",
        "HYPOTHESIS",
        "DENIAL",
        "ACCUSATION",
        "MEMORY",
        "EVALUATION",
        "INTERPRETATION",
        "PREDICTION",
        "COMMITMENT",
        "temporal_scope",
        "PAST",
        "PRESENT",
        "FUTURE",
        "ATEMPORAL",
        "semantic function",
        "surface verb",
        "saying claims is not automatically PREDICTION",
        "future action by the speaker is COMMITMENT",
        "future external event is PREDICTION",
        "believes, thinks, misunderstands, or takes an unhedged stance is BELIEF",
        "narrator or character states an unhedged fact is FACTUAL_ASSERTION",
        "Do not output EventProposalV1",
        "Do not output EntityProposalV1",
        "StoryBible",
        "EvidenceRefV1",
        "quote_text",
        "UNVERIFIED",
        "reality_layer",
        "JSON only",
        "Do not treat ordinary actions, events, or entity names as claims.",
    ]:
        assert expected in prompt


def test_claim_extraction_agent_prompt_requires_verbatim_contiguous_evidence() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "She denied opening it."}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for expected in [
        "one contiguous substring",
        "zero-based offsets relative",
        "never document-level offsets",
        "If a quote_text appears in more than one selected chunk",
        "Before returning each claim, verify quote_text",
        "If you cannot copy an exact supporting quote_text, omit that claim",
        "Do not normalize punctuation, whitespace, or quotation marks",
        "claim_text may be a faithful paraphrase",
        "quote_text must be verbatim source text",
    ]:
        assert expected in prompt


def test_claim_extraction_agent_prompt_contains_classification_examples() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "She believed it would rain."}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for expected in [
        "A character believes the seal is fake -> BELIEF",
        "A character vows to open the gate -> COMMITMENT",
        "A source predicts the bridge will collapse -> PREDICTION",
        "A narrator states a world rule -> FACTUAL_ASSERTION + ATEMPORAL",
        "ordinary actions belong to EventProposalV1",
    ]:
        assert expected in prompt


def test_claim_extraction_agent_prompt_prioritizes_epistemic_boundaries() -> None:
    provider = FakeProvider()
    agent = ClaimExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "他应该已经到了。"}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for expected in [
        "FACTUAL_ASSERTION is never a fallback label",
        "HYPOTHESIS before EVALUATION, INTERPRETATION, and FACTUAL_ASSERTION",
        "应该算是达到了门槛 -> HYPOTHESIS",
        "苏幼微认为周元帮助她只是看中她的美貌 -> BELIEF",
        "这门术法的杀伤力惊人 -> EVALUATION",
        "踏入养气境才能算登堂入室 -> FACTUAL_ASSERTION + ATEMPORAL",
        "我想，他恐怕连尸体都没了 -> HYPOTHESIS",
        "EVALUATION",
    ]:
        assert expected in prompt


def test_claim_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = ClaimExtractionAgent.spec

    assert spec.agent_id == "claim-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "ClaimProposalBatchV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7
    assert spec.tools == []
