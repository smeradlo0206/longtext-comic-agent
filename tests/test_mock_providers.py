import pytest

from comic_agent.providers.mocks import MockImageProvider, MockLLMProvider, MockMode
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalV1


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
