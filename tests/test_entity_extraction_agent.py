from typing import TypeVar

from pydantic import BaseModel

from comic_agent.agents.entity_extraction import EntityExtractionAgent
from comic_agent.schemas.narrative import EntityProposalBatchV1

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
                "batch_id": "entity-batch-1",
                "entities": [
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
                    },
                    {
                        "proposal_id": "entity-2",
                        "entity_type": "ORGANIZATION",
                        "canonical_name": "Blue Hall",
                        "aliases": [],
                        "evidence_refs": [
                            {
                                "chunk_id": "chunk-1",
                                "quote_text": "Blue Hall",
                            }
                        ],
                        "confidence": 0.82,
                    },
                ],
            }
        )


def test_entity_extraction_agent_calls_provider_and_returns_entity_batch() -> None:
    provider = FakeProvider()
    agent = EntityExtractionAgent(provider)

    batch = agent.run(
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

    assert isinstance(batch, EntityProposalBatchV1)
    assert batch.batch_id == "entity-batch-1"
    assert [entity.proposal_id for entity in batch.entities] == ["entity-1", "entity-2"]
    assert batch.entities[0].canonical_name == "Lin Fan"
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
        "EntityProposalBatchV1",
        "non-empty entities array",
        "Do not return a single EntityProposalV1",
        "Do not return another mode's batch",
        "entities",
        "number of entities must be based on real entities, not chunk count",
        "multiple entities",
        "same entity appears across chunks, output it once",
        "source_chunks",
        "Do not invent",
        "canonical_name",
        "aliases",
        "quote_text",
        "EvidenceRef",
        "JSON only",
        "StoryBible",
        "Do not treat ordinary actions, events, or claims as entities.",
    ]:
        assert expected in prompt


def test_entity_extraction_agent_prompt_prevents_long_reasoning() -> None:
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
    for expected in [
        "Do not reason step by step.",
        "Do not list candidate entities.",
        "Do not explain your choice.",
        "Return final EntityProposalBatchV1 JSON only.",
    ]:
        assert expected in prompt


def test_entity_extraction_agent_prompt_defines_entity_type_decision_table() -> None:
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
    for expected in [
        "CHARACTER: human beings or entities with a clear personhood",
        "CREATURE: non-human animals, demon beasts, magical beasts, spirit beasts, or monsters.",
        "LOCATION: places, regions, sect sites, or spaces",
        "ORGANIZATION: sects, dynasties, factions, families, or teams",
        "OBJECT: artifacts, weapons, tokens, pills, and important reusable objects",
        "ABILITY: cultivation methods, source arts, moves, abilities, techniques, or skills",
        "CONCEPT: realms, rules, institutions, power systems, and world-setting concepts",
        "Do not treat ordinary actions, event results, or character judgments as entities.",
    ]:
        assert expected in prompt


def test_entity_extraction_prompt_distinguishes_creatures_from_characters() -> None:
    provider = FakeProvider()
    agent = EntityExtractionAgent(provider)

    agent.run(
        {
            "project_id": "project-1",
            "source_chunk_ids": ["chunk-1"],
            "source_chunks": [{"chunk_id": "chunk-1", "text": "A named beast appears."}],
        }
    )

    prompt = str(provider.requests[0]["system_prompt"])
    for expected in ["CREATURE", "non-human", "creature_subtype", "Do not invent a subtype."]:
        assert expected in prompt


def test_entity_extraction_agent_prompt_hardens_names_aliases_and_evidence() -> None:
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
    for expected in [
        "canonical_name must come from source text or be directly supported by source text.",
        "Do not invent or complete missing names.",
        "Do not use a long description as canonical_name.",
        "aliases may only contain explicit aliases or forms of address present in source text.",
        "Do not infer aliases.",
        "Do not put identity descriptions, adjectives, or relationship descriptions in aliases.",
        "If there are no explicit aliases, use aliases=[].",
        "quote_text must be copied verbatim from the selected source chunk.",
        "Do not paraphrase, summarize, translate, merge, or rewrite quote_text.",
        "Prefer a 2-40 Chinese character quote",
    ]:
        assert expected in prompt


def test_entity_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = EntityExtractionAgent.spec

    assert spec.agent_id == "entity-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "EntityProposalBatchV1"
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
