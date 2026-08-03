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


def test_event_extraction_agent_request_includes_prompt_and_context() -> None:
    provider = FakeProvider()
    agent = EventExtractionAgent(provider)
    input_context = {
        "project_id": "project-1",
        "source_chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
        "source_chunks": [
            {"chunk_id": "chunk-1", "text": "First source chunk."},
            {"chunk_id": "chunk-2", "text": "Second source chunk."},
            {"chunk_id": "chunk-3", "text": "Third source chunk."},
        ],
    }

    agent.run(input_context)

    request = provider.requests[0]
    assert set(request) == {"system_prompt", "user_prompt", "input_context"}
    assert request["input_context"] == input_context
    assert "project_id" in str(request["user_prompt"])
    assert "source_chunk_ids" in str(request["user_prompt"])
    assert "source_chunks" in str(request["user_prompt"])


def test_event_extraction_prompt_contains_v01_constraints() -> None:
    provider = FakeProvider()
    agent = EventExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "First source chunk."}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for expected in [
        "exactly one",
        "EventProposalV1",
        "source_chunks",
        "quote_text",
        "Do not invent",
        "JSON only",
        "ClaimProposalV1",
        "KnowledgeStateProposalV1",
        "canonical story data",
        "Return final JSON directly.",
        "Do not include reasoning.",
        "Do not reason step by step.",
        "Do not list candidate events.",
        "Do not explain your choice.",
        "Select one concrete, evidence-backed event quickly.",
        "Keep summary concise.",
        "under 30 Chinese characters",
        "mostly background or setup",
        "single most salient event",
        "shortest exact quote",
        "shortest exact source quote",
        "copied verbatim",
        "Do not paraphrase, summarize, translate, merge, or rewrite quote_text.",
        "If quote_start/quote_end are uncertain",
        "quote_text must exact-match the chunk text",
        "6-40 Chinese character quote",
    ]:
        assert expected in prompt


def test_event_extraction_user_prompt_is_concise_and_context_focused() -> None:
    provider = FakeProvider()
    agent = EventExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "First source chunk."}],
        }
    )

    user_prompt = str(provider.requests[0]["user_prompt"])
    assert len(user_prompt) <= 140
    assert "project_id" in user_prompt
    assert "source_chunk_ids" in user_prompt
    assert "source_chunks" in user_prompt
    assert "Do not invent" not in user_prompt
    assert "ClaimProposalV1" not in user_prompt


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
