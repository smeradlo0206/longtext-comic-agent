import pytest

from comic_agent.agents.mocks import MockEventAgent
from comic_agent.providers.mocks import MockImageProvider, MockLLMProvider, MockMode
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.workflow import AgentRunV1, ProviderResultV1, ProviderType
from comic_agent.services.document_parser import DocumentParser


def test_mock_llm_provider_returns_structured_model() -> None:
    provider = MockLLMProvider(
        response={
            "proposal_id": "proposal-1",
            "event_type": "handoff",
            "summary": "Chen Ye gives Lin Xia an umbrella.",
            "participant_ids": ["char-chen", "char-lin"],
            "location_id": None,
            "evidence_refs": [{"chunk_id": "chunk-1"}],
            "confidence": 0.9,
            "reality_layer": "PRIMARY",
        },
    )

    result = provider.structured_generate({"prompt": "extract"}, EventProposalV1)

    assert result.evidence_refs == [EvidenceRefV1(chunk_id="chunk-1")]


def test_mock_llm_provider_can_return_schema_error() -> None:
    provider = MockLLMProvider(mode=MockMode.SCHEMA_ERROR, response={"proposal_id": "bad"})

    with pytest.raises(ValueError, match="schema"):
        provider.structured_generate({"prompt": "extract"}, EventProposalV1)


def test_mock_llm_provider_can_timeout() -> None:
    provider = MockLLMProvider(mode=MockMode.TIMEOUT)

    with pytest.raises(TimeoutError):
        provider.structured_generate({"prompt": "extract"}, EventProposalV1)


def test_mock_image_provider_returns_predictable_uri() -> None:
    provider = MockImageProvider()

    result = provider.generate({"panel_id": "panel-1"})

    assert result.storage_uri == "mock://images/panel-1.png"
    assert result.width == 1024
    assert result.height == 1024


def test_mock_event_agent_output_can_be_recorded_as_agent_run() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\n陈野把伞递给林夏。",
    )
    chunk = parsed.chunks[0]
    provider = MockLLMProvider(
        response={
            "proposal_id": "proposal-1",
            "event_type": "handoff",
            "summary": "陈野把伞递给林夏。",
            "participant_ids": ["char-chen", "char-lin"],
            "location_id": None,
            "evidence_refs": [{"chunk_id": chunk.chunk_id, "quote_text": "伞"}],
            "confidence": 0.9,
            "reality_layer": "PRIMARY",
        },
    )
    agent = MockEventAgent(provider)

    proposal = agent.run({"source_chunks": [chunk.model_dump(mode="json")]})
    provider_result = ProviderResultV1(
        provider_result_id="provider-result-1",
        provider_name="mock-llm",
        provider_type=ProviderType.MOCK,
        output_schema="EventProposalV1",
        structured_output=proposal.model_dump(mode="json"),
        success=True,
    )
    agent_run = AgentRunV1(
        agent_run_id="agent-run-1",
        project_id="project-1",
        agent_name="MockEventAgent",
        input_chunk_ids=[chunk.chunk_id],
        output_proposal_ids=[proposal.proposal_id],
        output_schema="EventProposalV1",
        provider_result_id=provider_result.provider_result_id,
        provider_result=provider_result,
        status="SUCCEEDED",
    )

    assert isinstance(proposal, EventProposalV1)
    assert proposal.evidence_refs
    assert proposal.evidence_refs[0].chunk_id == chunk.chunk_id
    assert proposal.evidence_refs[0].chunk_id in agent_run.input_chunk_ids
    assert agent_run.output_proposal_ids == [proposal.proposal_id]
    assert agent_run.provider_result is not None
    assert agent_run.provider_result.structured_output["proposal_id"] == proposal.proposal_id
