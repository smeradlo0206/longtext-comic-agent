from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.agents.knowledge_state_extraction import (
    KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT,
    KnowledgeStateExtractionAgent,
)
from comic_agent.schemas.narrative import KnowledgeStateProposalBatchV1

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class FakeKnowledgeStateProvider:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []
        self.output_models: list[type[BaseModel]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.requests.append(request)
        self.output_models.append(output_model)
        return output_model.model_validate(self.response)


def _input_context(text: str) -> dict[str, object]:
    return {
        "project_id": "project-1",
        "source_chunk_ids": ["chunk-1"],
        "source_chunks": [{"chunk_id": "chunk-1", "text": text}],
    }


def _state(
    proposal_id: str,
    quote: str,
    *,
    target_text: str = "门后有路",
) -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "proposal_id": proposal_id,
        "subject": {
            "mention_text": "甲",
            "entity_proposal_id": None,
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "target_kind": "WORLD_FACT",
            "target_text": target_text,
            "proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "epistemic_status": "SUSPECTS",
        "epistemic_basis": "INFERRED",
        "reality_layer": "PRIMARY",
        "evidence_refs": [{"chunk_id": "chunk-1", "quote_text": quote}],
        "confidence": 0.8,
    }


def test_knowledge_state_agent_spec_is_bounded_proposal_only_and_evidence_required() -> None:
    spec = KnowledgeStateExtractionAgent.spec

    assert spec.agent_id == "knowledge-state-extraction-agent"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "KnowledgeStateProposalBatchV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3


def test_knowledge_state_prompt_maps_disbelief_of_a_rumor_to_its_world_fact_content() -> None:
    prompt = " ".join(KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT.split())

    assert "BELIEVES, SUSPECTS, and DISBELIEVES must use WORLD_FACT or EVENT, never CLAIM" in prompt
    assert 'DISBELIEVES + WORLD_FACT + "山中有鬼"' in prompt
    assert 'DISBELIEVES + CLAIM + "山中有鬼的传言"' in prompt


def test_knowledge_state_agent_uses_structured_batch_model_and_returns_multiple_states() -> None:
    provider = FakeKnowledgeStateProvider(
        {
            "batch_id": "knowledge-batch-1",
            "states": [
                _state("knowledge-1", "甲怀疑门后有路"),
                _state("knowledge-2", "甲怀疑门后有路", target_text="门后有陷阱"),
            ],
        }
    )
    agent = KnowledgeStateExtractionAgent(provider)

    result = agent.run(_input_context("甲怀疑门后有路"))

    assert isinstance(result, KnowledgeStateProposalBatchV1)
    assert [state.proposal_id for state in result.states] == ["knowledge-1", "knowledge-2"]
    assert provider.output_models == [KnowledgeStateProposalBatchV1]


def test_knowledge_state_batch_rejects_semantically_duplicate_states_with_different_ids() -> None:
    with pytest.raises(ValidationError, match="semantic duplicate"):
        KnowledgeStateProposalBatchV1.model_validate(
            {
                "batch_id": "knowledge-batch-duplicate",
                "states": [
                    _state("knowledge-1", "甲怀疑门后有路"),
                    _state("knowledge-2", "甲怀疑门后有路"),
                ],
            }
        )


def test_knowledge_state_agent_accepts_empty_batch_for_speech_without_explicit_mental_state() -> (
    None
):
    provider = FakeKnowledgeStateProvider({"batch_id": "knowledge-batch-empty", "states": []})

    result = KnowledgeStateExtractionAgent(provider).run(_input_context("甲说：门后有路。"))

    assert result.states == []
    assert provider.output_models == [KnowledgeStateProposalBatchV1]


def test_knowledge_state_agent_accepts_empty_batch_for_presence_without_explicit_knowledge() -> (
    None
):
    provider = FakeKnowledgeStateProvider({"batch_id": "knowledge-batch-empty", "states": []})

    result = KnowledgeStateExtractionAgent(provider).run(_input_context("甲在场，看见门打开。"))

    assert result.states == []


def test_knowledge_state_prompt_states_the_epistemic_and_output_boundaries() -> None:
    prompt = KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT

    for required_text in (
        "explicit",
        "states\nmay be empty",
        "Seeing, presence, hearing a sentence, narrator",
        "never invent IDs",
        "exact verbatim EvidenceRefV1 quote",
        "final JSON",
        "StoryBible",
        "KNOWS",
        "HEARD",
        "SUSPECTS",
        "BELIEVES",
        "DISBELIEVES",
        "UNAWARE",
        "unique proposal_id",
        "only once",
        "KNOWS + OBSERVED",
        "seeing an object",
        "hidden content",
        "Never upgrade HEARD, SUSPECTS, or BELIEVES to KNOWS",
    ):
        assert required_text in prompt


def test_knowledge_state_prompt_rejects_direct_speech_as_belief_without_mental_evidence() -> None:
    prompt = KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT

    assert "A direct assertion alone is never BELIEVES" in prompt
    assert "return no Knowledge State for it" in prompt


def test_knowledge_state_prompt_leaves_missing_temporal_anchors_null() -> None:
    prompt = " ".join(KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT.split())

    assert "Default valid_from and valid_until to null" in prompt
    assert "Use an UNRESOLVED temporal anchor only when the source explicitly supplies" in prompt


def test_knowledge_state_prompt_stabilizes_target_kind_and_core_proposition_text() -> None:
    prompt = " ".join(KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT.split())

    for required_text in (
        "EVENT: only a concrete occurrence, discovery, change, or action.",
        (
            "WORLD_FACT: a proposition about the world, person, place, object, relationship, "
            "or fact state."
        ),
        (
            "CLAIM: only when the cognitive target is the statement, report, rumor, declaration, "
            "accusation, or promise itself."
        ),
        "HEARD does not imply target_kind=CLAIM.",
        "守卫故意隐瞒了山路的位置",
        "山中有鬼",
        "smallest complete, auditable core proposition",
        "speech frame into WORLD_FACT.",
        "Do not output both an atomic proposition and a composite proposition",
    ):
        assert required_text in prompt


def test_knowledge_state_prompt_requires_safe_optional_python_offsets() -> None:
    prompt = " ".join(KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT.split())

    assert "Default quote_start and quote_end to null" in prompt
    assert "Python half-open interval" in prompt
    assert "quote_end is the exclusive end" in prompt
    assert "Only provide both offsets when you can guarantee" in prompt
    assert "preserve its terminal punctuation" in prompt


def test_knowledge_state_prompt_classifies_concrete_actions_as_events() -> None:
    prompt = " ".join(KNOWLEDGE_STATE_EXTRACTION_SYSTEM_PROMPT.split())

    assert "leave, arrive, discover, die, happen, open, close, or change" in prompt
    assert "EVENT: only a concrete occurrence" in prompt


@pytest.mark.parametrize(
    "text",
    [
        "林舟说：信里有秘密。",
        "林舟匆匆从书桌旁走过。桌上放着一封染血的信，但他没有停下查看。",
        "林舟听到别人说矿洞封死了。",
        "林舟看见一封信，却没有拆开。",
    ],
)
def test_knowledge_state_agent_fixture_keeps_non_explicit_knowledge_as_empty_batch(
    text: str,
) -> None:
    provider = FakeKnowledgeStateProvider({"batch_id": "knowledge-batch-empty", "states": []})

    result = KnowledgeStateExtractionAgent(provider).run(_input_context(text))

    assert result.states == []


def test_knowledge_state_agent_fixture_allows_explicit_confirmed_observation() -> None:
    provider = FakeKnowledgeStateProvider(
        {
            "batch_id": "knowledge-batch-observed",
            "states": [
                _state(
                    "knowledge-observed",
                    "林舟亲眼看见火把熄灭，并确认矿洞入口已经封死。",
                    target_text="矿洞入口已经封死",
                )
                | {"epistemic_status": "KNOWS", "epistemic_basis": "OBSERVED"}
            ],
        }
    )

    result = KnowledgeStateExtractionAgent(provider).run(
        _input_context("林舟亲眼看见火把熄灭，并确认矿洞入口已经封死。")
    )

    assert result.states[0].epistemic_status == "KNOWS"
    assert result.states[0].epistemic_basis == "OBSERVED"
