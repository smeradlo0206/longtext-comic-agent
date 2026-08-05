from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.event_extraction import EventExtractionAgent
from comic_agent.schemas.narrative import EventProposalBatchV1

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
                "batch_id": "event-batch-1",
                "events": [
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
                    },
                    {
                        "proposal_id": "proposal-2",
                        "event_type": "bell_rang",
                        "summary": "钟声响起。",
                        "participant_ids": [],
                        "actor_resolution_status": "NOT_APPLICABLE",
                        "location_id": None,
                        "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": "钟声响起"}],
                        "confidence": 0.82,
                        "reality_layer": "PRIMARY",
                    },
                ],
            }
        )


def test_event_extraction_agent_calls_provider_and_returns_event_batch() -> None:
    provider = FakeProvider()
    agent = EventExtractionAgent(provider)

    batch = agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "陈野把伞递给林夏。钟声响起。"}],
        }
    )

    assert isinstance(batch, EventProposalBatchV1)
    assert batch.batch_id == "event-batch-1"
    assert [event.proposal_id for event in batch.events] == ["proposal-1", "proposal-2"]
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
        "exactly one EventProposalBatchV1",
        "EventProposalBatchV1",
        "1 or more EventProposalV1",
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
        "Extract all salient story events",
        "number of events must be based on actual story events, not chunk count",
        "one chunk contains multiple events",
        "multiple chunks narrate one continuous event",
        "Do not invent events to match chunk count.",
        "Do not duplicate the same event.",
        "Sort events by source order.",
        "Every event summary must be directly supported by its own evidence quote.",
        "If evidence only supports a narrower event, narrow that event summary.",
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


def test_event_extraction_prompt_requires_summary_supported_by_quote() -> None:
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
    assert (
        "summary must only state facts directly supported by "
        "that event's evidence quote"
    ) in prompt
    assert "Every actor, action, object, and outcome mentioned in each summary" in prompt
    assert "directly inferable from the quote" in prompt
    assert "If the quote only supports part of a larger event, narrow the summary" in prompt


def test_event_extraction_prompt_forbids_merged_adjacent_events() -> None:
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
    assert "Return 1 or more EventProposalV1 records inside events." in prompt
    assert "Do not merge adjacent events into one proposal." in prompt
    assert "If one chunk contains multiple events, output multiple events." in prompt
    assert "If multiple chunks narrate one continuous event, output one event." in prompt
    assert (
        "Do not combine action + later explanation/announcement/reaction into one event"
        in prompt
    )


def test_event_extraction_prompt_discourages_joined_event_type_labels() -> None:
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
    assert "Each event_type should name a single event" in prompt
    assert "not a merged category" in prompt
    assert "suppression_and_announcement" in prompt
    assert "Avoid joined labels" in prompt


def test_event_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = EventExtractionAgent.spec

    assert spec.agent_id == "event-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "EventProposalBatchV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7
