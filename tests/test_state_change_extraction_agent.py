import json
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.agents.state_change_extraction import (
    STATE_CHANGE_EXTRACTION_SYSTEM_PROMPT,
    StateChangeExtractionAgent,
)
from comic_agent.schemas import SourceChunkV1, StateChangeProposalBatchV1

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

_YUANZUN_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "local_eval" / "state_change_yuanzun_samples.json"
)


class FixtureFakeProvider:
    """Validate a fixed structured response without contacting a model provider."""

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


@pytest.fixture(scope="module")
def yuanzun_cases() -> dict[str, dict[str, object]]:
    fixture = json.loads(_YUANZUN_FIXTURE_PATH.read_text(encoding="utf-8"))
    return {case["case_id"]: case for case in fixture["cases"]}


def _source_chunk(case: dict[str, object]) -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=f"chunk-{case['case_id']}",
        document_id="local-eval-yuanzun",
        chapter_id=f"chapter-{case['source_line_start']}",
        project_id="local-eval",
        order=0,
        text=str(case["text"]),
        checksum="fixture-only",
    )


def _unresolved_change(
    source_chunk: SourceChunkV1,
    *,
    proposal_id: str,
    event_summary: str,
    mention_text: str,
    target_kind: str,
    attribute_path: str,
    new_value: str,
    quote_text: str,
    persistence_quote_text: str | None = None,
) -> dict[str, object]:
    assert quote_text in source_chunk.text
    if persistence_quote_text is not None:
        assert persistence_quote_text in source_chunk.text
    evidence_refs: list[dict[str, object]] = [
        {
            "chunk_id": source_chunk.chunk_id,
            "quote_start": None,
            "quote_end": None,
            "quote_text": quote_text,
        }
    ]
    if persistence_quote_text is not None:
        evidence_refs.append(
            {
                "chunk_id": source_chunk.chunk_id,
                "quote_start": None,
                "quote_end": None,
                "quote_text": persistence_quote_text,
            }
        )
    return {
        "schema_version": "1.2",
        "proposal_id": proposal_id,
        "event": {
            "event_summary": event_summary,
            "event_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "mention_text": mention_text,
            "target_kind": target_kind,
            "entity_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        "attribute_path": attribute_path,
        "old_value": None,
        "new_value": new_value,
        "persistent": persistence_quote_text is not None,
        "reality_layer": "PRIMARY",
        "evidence_refs": evidence_refs,
        "new_value_evidence_indexes": [0],
        "persistence_evidence_indexes": [1] if persistence_quote_text is not None else [],
        "confidence": 0.9,
    }


def _run_fixture_response(
    source_chunk: SourceChunkV1,
    response: dict[str, object],
) -> tuple[StateChangeProposalBatchV1, FixtureFakeProvider]:
    provider = FixtureFakeProvider(response)
    batch = StateChangeExtractionAgent(provider).run(
        {
            "source_chunk_ids": [source_chunk.chunk_id],
            "source_chunks": [source_chunk],
        }
    )
    return batch, provider


def test_state_change_extraction_agent_spec_is_bounded_and_proposal_only() -> None:
    spec = StateChangeExtractionAgent.spec

    assert spec.agent_id == "state-change-extraction-agent"
    assert spec.version == "0.1"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "StateChangeProposalBatchV1"
    assert spec.tools == []
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3
    assert spec.confidence_threshold == 0.7


def test_state_change_extraction_prompt_preserves_v13_source_only_contract() -> None:
    prompt = " ".join(STATE_CHANGE_EXTRACTION_SYSTEM_PROMPT.split())

    for required_text in (
        "StateChangeProposalBatchV1",
        'schema_version="1.3"',
        "changes=[]",
        "input_context.source_chunks",
        "input_context.source_chunk_ids",
        "complete evidence boundary",
        "scan every sentence in source order",
        "Do not stop after the first change",
        "another window",
        "old_value=null",
        "左臂渗出血珠",
        "木箱完好",
        "铁门合上",
        "药瓶 6 -> 4",
        "UNRESOLVED",
        "Do not invent event_proposal_id or entity_proposal_id",
        "new_value_evidence_indexes",
        "persistence_evidence_indexes",
        "persistent=true only when",
        "persistent=true is allowed only when",
        "continuing, permanent, from-now-on, long-term, or stable",
        "Collapse, close, recover, be injured, arrive, obtain, or put results alone "
        "do not constitute persistence evidence",
        "persistent=false",
        "persistence_evidence_indexes=[]",
        "event_summary only describes the minimal cause or local context",
        "Do not mix another target",
        "mention_text must be an exact name or pronoun",
        "runtime boundary check",
        "Do not turn \"他\" or \"她\" into an invented person",
        "health.injury",
        "life_status",
        "possession.holder",
        "physical.condition",
        "accessibility",
        "availability",
        "quantity",
        "role.status",
        "appearance.clothing",
        "appearance.hairstyle",
        "Part-whole target resolution is intentionally out of scope",
        "木箱",
        "箱盖",
        "CHARACTER only",
        "换上灰衣",
        "解开发绳，长发披下",
        "脸色苍白",
        "裂纹",
        "最终",
        "pure speech",
        "plan, promise, condition, hypothesis, wish, or prediction",
        "挥拳击中木板，木屑落下",
        "does not prove",
        "Python half-open interval",
        "exclusive end",
        "StoryBible",
        "final JSON only",
    ):
        assert required_text in prompt

    assert "states=[]" not in prompt


def test_rockery_fixture_declares_persistence_expectation_and_forbidden_output(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    case = yuanzun_cases["yuanzun-l001667-rockery-collapses"]

    assert case["expected_persistent"] is False
    assert case["forbidden_persistent"] is True
    assert "崩塌" in str(case["persistence_contract"])


def test_rockery_change_accepts_nonpersistent_output_from_real_fixture(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l001667-rockery-collapses"])
    change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-rockery-nonpersistent",
        event_summary="周元重拍假山",
        mention_text="假山",
        target_kind="OBJECT",
        attribute_path="physical.condition",
        new_value="崩塌",
        quote_text="假山直接崩塌下来。",
    )
    batch, _ = _run_fixture_response(
        source_chunk,
        {"schema_version": "1.2", "batch_id": "batch-rockery", "changes": [change]},
    )

    assert batch.changes[0].persistent is False
    assert batch.changes[0].persistence_evidence_indexes == []


def test_rockery_semantically_forbidden_persistent_output_is_not_silently_rewritten(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l001667-rockery-collapses"])
    change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-rockery-forbidden-persistent",
        event_summary="周元重拍假山",
        mention_text="假山",
        target_kind="OBJECT",
        attribute_path="physical.condition",
        new_value="崩塌",
        quote_text="假山直接崩塌下来。",
        persistence_quote_text="假山直接崩塌下来。",
    )
    batch, _ = _run_fixture_response(
        source_chunk,
        {"schema_version": "1.2", "batch_id": "batch-rockery-forbidden", "changes": [change]},
    )

    assert batch.changes[0].persistent is True
    assert batch.changes[0].persistence_evidence_indexes == [1]


def test_unresolved_target_name_must_appear_in_allowed_source_chunks(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000819-receives-black-pen"])
    change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-source-target-boundary",
        event_summary="周元接过黑笔",
        mention_text="不存在的人名",
        target_kind="CHARACTER",
        attribute_path="life_status",
        new_value="存活",
        quote_text="周元恭谨的接过这支黑笔",
    )

    with pytest.raises(ValueError, match="mention_text must appear"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-source-target-boundary",
                "changes": [change],
            },
        )


def test_unresolved_target_name_present_in_allowed_source_is_accepted(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000819-receives-black-pen"])
    change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-source-target-present",
        event_summary="周元接过黑笔",
        mention_text="周元",
        target_kind="OBJECT",
        attribute_path="possession.holder",
        new_value="周元",
        quote_text="周元恭谨的接过这支黑笔",
    )

    batch, _ = _run_fixture_response(
        source_chunk,
        {"schema_version": "1.2", "batch_id": "batch-source-target-present", "changes": [change]},
    )

    assert batch.changes[0].target is not None
    assert batch.changes[0].target.mention_text == "周元"


@pytest.mark.parametrize(
    (
        "case_id",
        "event_summary",
        "mention_text",
        "target_kind",
        "attribute_path",
        "new_value",
        "quote_text",
        "persistence_quote_text",
    ),
    [
        (
            "yuanzun-l000564-hidden-door-opens",
            "灵牌转动后石门裂开",
            "石门",
            "OBJECT",
            "accessibility",
            "开启",
            "缓缓的裂开了一扇厚重而隐秘的石门。",
            None,
        ),
        (
            "yuanzun-l000582-self-inflicted-injury",
            "他用小刀划过手腕",
            "他",
            "CHARACTER",
            "health.injury",
            "手腕受伤",
            "直接自手腕处划过，顿时鲜血滚滚流淌出来",
            None,
        ),
        (
            "yuanzun-l000641-enters-forest",
            "她踏入森林",
            "她",
            "CHARACTER",
            "location",
            "森林之中",
            "踏入森林之中",
            None,
        ),
        (
            "yuanzun-l000819-receives-black-pen",
            "周元接过黑笔",
            "黑笔",
            "OBJECT",
            "possession.holder",
            "周元",
            "周元恭谨的接过这支黑笔",
            None,
        ),
        (
            "yuanzun-l000887-space-collapses",
            "空间急速崩塌",
            "这片空间",
            "LOCATION",
            "physical.condition",
            "崩塌",
            "这片空间，急速崩塌。",
            None,
        ),
        (
            "yuanzun-l001667-rockery-collapses",
            "拳头重拍假山后假山崩塌",
            "假山",
            "OBJECT",
            "physical.condition",
            "崩塌",
            "假山直接崩塌下来。",
            None,
        ),
    ],
)
def test_state_change_extraction_accepts_each_yuanzun_candidate_from_one_source_chunk(
    yuanzun_cases: dict[str, dict[str, object]],
    case_id: str,
    event_summary: str,
    mention_text: str,
    target_kind: str,
    attribute_path: str,
    new_value: str,
    quote_text: str,
    persistence_quote_text: str | None,
) -> None:
    source_chunk = _source_chunk(yuanzun_cases[case_id])
    response = {
        "schema_version": "1.2",
        "batch_id": f"batch-{case_id}",
        "changes": [
            _unresolved_change(
                source_chunk,
                proposal_id=f"proposal-{case_id}",
                event_summary=event_summary,
                mention_text=mention_text,
                target_kind=target_kind,
                attribute_path=attribute_path,
                new_value=new_value,
                quote_text=quote_text,
                persistence_quote_text=persistence_quote_text,
            )
        ],
    }

    batch, provider = _run_fixture_response(source_chunk, response)

    assert isinstance(batch, StateChangeProposalBatchV1)
    assert batch.schema_version == "1.2"
    assert len(batch.changes) == 1
    change = batch.changes[0]
    assert change.target is not None
    assert change.event is not None
    assert change.target.resolution_status == "UNRESOLVED"
    assert change.target.entity_proposal_id is None
    assert change.target.proposal_schema is None
    assert change.event.resolution_status == "UNRESOLVED"
    assert change.event.event_proposal_id is None
    assert change.event.proposal_schema is None
    assert str(change.attribute_path) == attribute_path
    assert str(change.target.target_kind) == target_kind
    assert change.old_value is None
    assert change.new_value == new_value
    assert change.persistent is (persistence_quote_text is not None)
    assert change.persistence_evidence_indexes == ([1] if persistence_quote_text else [])
    assert change.new_value_evidence_indexes == [0]
    evidence = change.evidence_refs[0]
    assert evidence.chunk_id == source_chunk.chunk_id
    assert evidence.quote_text == quote_text
    assert quote_text in source_chunk.text
    assert provider.output_models == [StateChangeProposalBatchV1]
    assert provider.requests[0]["input_context"] == {
        "source_chunk_ids": [source_chunk.chunk_id],
        "source_chunks": [source_chunk],
    }


@pytest.mark.parametrize(
    ("case_id", "change_specs"),
    [
        (
            "yuanzun-l003326-possession-and-location",
            [
                (
                    "挖出兽魂晶",
                    "兽魂晶",
                    "OBJECT",
                    "possession.holder",
                    "他",
                    "将五头风灵狼脑袋中的兽魂晶挖了出来",
                ),
                ("返回溪谷", "他", "CHARACTER", "location", "溪谷中", "回到了溪谷中。"),
            ],
        ),
        (
            "yuanzun-l005023-receives-and-opens-box",
            [
                (
                    "周元接过玉盒",
                    "玉盒",
                    "OBJECT",
                    "possession.holder",
                    "周元",
                    "小心翼翼的接过玉盒",
                ),
                ("周元打开玉盒", "玉盒", "OBJECT", "physical.condition", "打开", "将其打开"),
            ],
        ),
        (
            "yuanzun-l005651-stores-fruit",
            [
                ("周元关闭玉盒", "玉盒", "OBJECT", "physical.condition", "关闭", "立即关闭了玉盒"),
                (
                    "周元收起玉婴果",
                    "玉婴果",
                    "OBJECT",
                    "location",
                    "乾坤囊中",
                    "将其收入乾坤囊中。",
                ),
            ],
        ),
        (
            "yuanzun-l006583-dungeon-door-and-barrier-close",
            [
                ("青铜门关闭", "青铜门", "OBJECT", "accessibility", "关闭", "青铜门关闭"),
                (
                    "源纹结界恢复",
                    "源纹结界",
                    "OBJECT",
                    "accessibility",
                    "恢复",
                    "源纹结界也是渐渐的恢复",
                ),
            ],
        ),
        (
            "yuanzun-l007087-exits-and-closes-door",
            [
                ("少女走出院房", "清丽少女", "CHARACTER", "location", "院房外", "轻轻的走出"),
                ("少女关闭房门", "房门", "OBJECT", "accessibility", "关闭", "关闭房门。"),
            ],
        ),
    ],
)
def test_state_change_extraction_keeps_each_yuanzun_multi_candidate_change(
    yuanzun_cases: dict[str, dict[str, object]],
    case_id: str,
    change_specs: list[tuple[str, str, str, str, str, str]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases[case_id])
    changes = [
        _unresolved_change(
            source_chunk,
            proposal_id=f"proposal-{case_id}-{index}",
            event_summary=event_summary,
            mention_text=mention_text,
            target_kind=target_kind,
            attribute_path=attribute_path,
            new_value=new_value,
            quote_text=quote_text,
        )
        for index, (
            event_summary,
            mention_text,
            target_kind,
            attribute_path,
            new_value,
            quote_text,
        ) in enumerate(change_specs, start=1)
    ]

    batch, provider = _run_fixture_response(
        source_chunk,
        {
            "schema_version": "1.2",
            "batch_id": f"batch-{case_id}",
            "changes": changes,
        },
    )

    assert len(batch.changes) == len(change_specs)
    assert [change.proposal_id for change in batch.changes] == [
        f"proposal-{case_id}-{index}" for index in range(1, len(change_specs) + 1)
    ]
    assert len({change.proposal_id for change in batch.changes}) == len(change_specs)
    assert all(len(change.evidence_refs) == 1 for change in batch.changes)
    assert all(change.new_value_evidence_indexes == [0] for change in batch.changes)
    assert all(change.persistence_evidence_indexes == [] for change in batch.changes)
    assert all(
        change.evidence_refs[0].chunk_id == source_chunk.chunk_id
        for change in batch.changes
    )
    assert all(
        change.evidence_refs[0].quote_text in source_chunk.text for change in batch.changes
    )
    semantic_values = [
        (
            change.event.event_summary if change.event else None,
            change.target.mention_text if change.target else None,
            str(change.attribute_path),
            change.new_value,
        )
        for change in batch.changes
    ]
    assert len(set(semantic_values)) == len(change_specs)
    assert provider.requests[0]["input_context"]["source_chunks"] == [source_chunk]  # type: ignore[index]


@pytest.mark.parametrize(
    "case_id",
    [
        "yuanzun-l006297-abandons-theft-intent",
        "yuanzun-l004601-social-reaction-boundary",
    ],
)
def test_state_change_extraction_returns_empty_batch_for_yuanzun_negative_cases(
    yuanzun_cases: dict[str, dict[str, object]], case_id: str
) -> None:
    source_chunk = _source_chunk(yuanzun_cases[case_id])

    batch, provider = _run_fixture_response(
        source_chunk,
        {
            "schema_version": "1.2",
            "batch_id": f"batch-{case_id}",
            "changes": [],
        },
    )

    assert isinstance(batch, StateChangeProposalBatchV1)
    assert batch.schema_version == "1.2"
    assert batch.changes == []
    assert "states" not in provider.response
    assert provider.requests[0]["input_context"]["source_chunks"] == [source_chunk]  # type: ignore[index]
    assert provider.requests[0]["input_context"]["source_chunk_ids"] == [source_chunk.chunk_id]  # type: ignore[index]


def test_state_change_extraction_rejects_fake_resolved_candidate_links(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000819-receives-black-pen"])
    invalid_change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-resolved-link",
        event_summary="周元接过黑笔",
        mention_text="黑笔",
        target_kind="OBJECT",
        attribute_path="possession.holder",
        new_value="周元",
        quote_text="周元恭谨的接过这支黑笔",
    )
    invalid_change["event"] = {
        "event_summary": "周元接过黑笔",
        "event_proposal_id": "invented-event-proposal",
        "proposal_schema": "EventProposalV1",
        "resolution_status": "RESOLVED",
    }
    invalid_change["target"] = {
        "mention_text": "黑笔",
        "target_kind": "OBJECT",
        "entity_proposal_id": "invented-entity-proposal",
        "proposal_schema": "EntityProposalV1",
        "resolution_status": "RESOLVED",
    }

    with pytest.raises(ValueError, match="UNRESOLVED"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-resolved-link",
                "changes": [invalid_change],
            },
        )


def test_state_change_extraction_schema_rejects_invalid_local_evidence_index(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-invalid-evidence-index",
        event_summary="他用小刀划过手腕",
        mention_text="他",
        target_kind="CHARACTER",
        attribute_path="health.injury",
        new_value="手腕受伤",
        quote_text="直接自手腕处划过，顿时鲜血滚滚流淌出来",
    )
    invalid_change["new_value_evidence_indexes"] = [1]

    with pytest.raises(ValidationError, match="out-of-range"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-invalid-evidence-index",
                "changes": [invalid_change],
            },
        )


@pytest.mark.parametrize(
    "case_id",
    [
        "yuanzun-l000099-emotional-physical-boundary",
        "yuanzun-l000245-cultivation-progression",
        "yuanzun-l001122-source-qi-exhausted",
        "yuanzun-l001501-first-meridian-opened",
        "yuanzun-l001659-second-meridian-opened",
        "yuanzun-l003477-opens-six-meridians-for-combat",
        "yuanzun-l004317-soul-level-advances",
        "yuanzun-l008196-long-journey-summary",
        "yuanzun-l028905-stores-weapon-in-body",
    ],
)
def test_state_change_extraction_accepts_empty_batch_for_yuanzun_boundary_cases(
    yuanzun_cases: dict[str, dict[str, object]], case_id: str
) -> None:
    source_chunk = _source_chunk(yuanzun_cases[case_id])

    batch, provider = _run_fixture_response(
        source_chunk,
        {
            "schema_version": "1.2",
            "batch_id": f"batch-{case_id}",
            "changes": [],
        },
    )

    assert batch.schema_version == "1.2"
    assert batch.changes == []


def test_state_change_extraction_rejects_evidence_from_unselected_context_chunk(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    selected_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    extra_chunk = _source_chunk(yuanzun_cases["yuanzun-l000819-receives-black-pen"])
    invalid_change = _unresolved_change(
        extra_chunk,
        proposal_id="proposal-extra-context-evidence",
        event_summary="周元接过黑笔",
        mention_text="黑笔",
        target_kind="OBJECT",
        attribute_path="possession.holder",
        new_value="周元",
        quote_text="周元恭谨的接过这支黑笔",
    )
    provider = FixtureFakeProvider(
        {
            "schema_version": "1.2",
            "batch_id": "batch-extra-context-evidence",
            "changes": [invalid_change],
        }
    )

    with pytest.raises(ValueError, match="source_chunk_ids"):
        StateChangeExtractionAgent(provider).run(
            {
                "source_chunk_ids": [selected_chunk.chunk_id],
                "source_chunks": [selected_chunk, extra_chunk],
            }
        )


def test_state_change_extraction_rejects_incomplete_source_chunk_dict(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    valid_change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-incomplete-source-chunk",
        event_summary="他用小刀划过手腕",
        mention_text="他",
        target_kind="CHARACTER",
        attribute_path="health.injury",
        new_value="手腕受伤",
        quote_text="直接自手腕处划过，顿时鲜血滚滚流淌出来",
    )
    provider = FixtureFakeProvider(
        {
            "schema_version": "1.2",
            "batch_id": "batch-incomplete-source-chunk",
            "changes": [valid_change],
        }
    )

    with pytest.raises(ValueError, match="SourceChunkV1"):
        StateChangeExtractionAgent(provider).run(
            {
                "source_chunk_ids": [source_chunk.chunk_id],
                "source_chunks": [
                    {
                        "chunk_id": source_chunk.chunk_id,
                        "text": source_chunk.text,
                    }
                ],
            }
        )


def test_state_change_extraction_rejects_evidence_quote_outside_input_source_chunk(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _unresolved_change(
        source_chunk,
        proposal_id="proposal-outside-quote",
        event_summary="他用小刀划过手腕",
        mention_text="他",
        target_kind="CHARACTER",
        attribute_path="health.injury",
        new_value="手腕受伤",
        quote_text="直接自手腕处划过，顿时鲜血滚滚流淌出来",
    )
    invalid_change["evidence_refs"] = [
        {
            "chunk_id": source_chunk.chunk_id,
            "quote_start": None,
            "quote_end": None,
            "quote_text": "并非输入片段中的证据",
        }
    ]

    with pytest.raises(ValueError, match="quote_text"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-outside-quote",
                "changes": [invalid_change],
            },
        )


def test_state_change_extraction_rejects_evidence_reference_to_unknown_input_chunk(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-unknown-chunk")
    invalid_change["evidence_refs"] = [
        {
            "chunk_id": "chunk-not-in-input",
            "quote_start": None,
            "quote_end": None,
            "quote_text": "直接自手腕处划过，顿时鲜血滚滚流淌出来",
        }
    ]

    with pytest.raises(ValueError, match="input SourceChunk"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-unknown-chunk",
                "changes": [invalid_change],
            },
        )


def _valid_yuanzun_injury_change(
    source_chunk: SourceChunkV1, proposal_id: str
) -> dict[str, object]:
    return _unresolved_change(
        source_chunk,
        proposal_id=proposal_id,
        event_summary="他用小刀划过手腕",
        mention_text="他",
        target_kind="CHARACTER",
        attribute_path="health.injury",
        new_value="手腕受伤",
        quote_text="直接自手腕处划过，顿时鲜血滚滚流淌出来",
    )


def _assert_yuanzun_schema_rejection(
    source_chunk: SourceChunkV1, change: dict[str, object], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-invalid-v12",
                "changes": [change],
            },
        )


def test_state_change_extraction_schema_rejects_unresolved_links_with_candidate_ids(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-unresolved-links")
    invalid_change["event"] = {
        "event_summary": "他用小刀划过手腕",
        "event_proposal_id": "candidate-event",
        "proposal_schema": "EventProposalV1",
        "resolution_status": "UNRESOLVED",
    }
    invalid_change["target"] = {
        "mention_text": "他",
        "target_kind": "CHARACTER",
        "entity_proposal_id": "candidate-entity",
        "proposal_schema": "EntityProposalV1",
        "resolution_status": "UNRESOLVED",
    }

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "UNRESOLVED")


def test_state_change_extraction_schema_rejects_legacy_reference_fields(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-legacy-fields")
    invalid_change["event_id"] = "legacy-event"
    invalid_change["target_entity_id"] = "legacy-target"

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "legacy")


def test_state_change_extraction_schema_rejects_attribute_path_outside_v12_allowlist(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-invalid-path")
    invalid_change["attribute_path"] = "cultivation.level"

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "controlled")


@pytest.mark.parametrize(
    ("invalid_new_value", "case_name"),
    [
        (None, "null"),
        ("", "blank"),
        ({"status": "受伤"}, "object"),
        (["受伤"], "array"),
    ],
)
def test_state_change_extraction_schema_rejects_non_scalar_or_empty_new_value(
    yuanzun_cases: dict[str, dict[str, object]],
    invalid_new_value: object,
    case_name: str,
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(
        source_chunk, f"proposal-invalid-new-value-{case_name}"
    )
    invalid_change["new_value"] = invalid_new_value

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "new_value")


@pytest.mark.parametrize("unknown_old_value", ["未知", "不明"])
def test_state_change_extraction_schema_rejects_unknown_old_value_placeholders(
    yuanzun_cases: dict[str, dict[str, object]], unknown_old_value: str
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(
        source_chunk, f"proposal-unknown-old-value-{unknown_old_value}"
    )
    invalid_change["old_value"] = unknown_old_value

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "unknown placeholder")


@pytest.mark.parametrize(
    ("indexes", "case_name", "match"),
    [
        ([], "empty", "must not be empty"),
        ([0, 0], "duplicate", "must not contain duplicate"),
        ([1], "out-of-range", "out-of-range"),
    ],
)
def test_state_change_extraction_schema_rejects_invalid_new_value_evidence_indexes(
    yuanzun_cases: dict[str, dict[str, object]],
    indexes: list[int],
    case_name: str,
    match: str,
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(
        source_chunk, f"proposal-invalid-indexes-{case_name}"
    )
    invalid_change["new_value_evidence_indexes"] = indexes

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, match)


def test_state_change_extraction_schema_rejects_persistent_change_without_evidence_index(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-persistent-without-index")
    invalid_change["persistent"] = True
    invalid_change["persistence_evidence_indexes"] = []

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "persistence_evidence_indexes")


def test_state_change_extraction_schema_rejects_nonpersistent_change_with_persistence_index(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-nonpersistent-with-index")
    invalid_change["persistence_evidence_indexes"] = [0]

    _assert_yuanzun_schema_rejection(source_chunk, invalid_change, "persistent=false")


def test_state_change_extraction_rejects_evidence_offsets_not_matching_quote_text(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    invalid_change = _valid_yuanzun_injury_change(source_chunk, "proposal-invalid-offsets")
    invalid_change["evidence_refs"] = [
        {
            "chunk_id": source_chunk.chunk_id,
            "quote_start": 0,
            "quote_end": 2,
            "quote_text": "直接自手腕处划过，顿时鲜血滚滚流淌出来",
        }
    ]

    with pytest.raises(ValueError, match="offsets"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-invalid-offsets",
                "changes": [invalid_change],
            },
        )


def test_state_change_extraction_schema_rejects_duplicate_proposal_ids_in_one_batch(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    duplicate_change = _valid_yuanzun_injury_change(source_chunk, "proposal-duplicate")

    with pytest.raises(ValidationError, match="unique proposal_id"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-duplicate-id",
                "changes": [duplicate_change, duplicate_change],
            },
        )


def test_state_change_extraction_schema_rejects_semantic_duplicates_in_one_batch(
    yuanzun_cases: dict[str, dict[str, object]],
) -> None:
    source_chunk = _source_chunk(yuanzun_cases["yuanzun-l000582-self-inflicted-injury"])
    first_change = _valid_yuanzun_injury_change(source_chunk, "proposal-semantic-first")
    second_change = _valid_yuanzun_injury_change(source_chunk, "proposal-semantic-second")

    with pytest.raises(ValidationError, match="semantic duplicate"):
        _run_fixture_response(
            source_chunk,
            {
                "schema_version": "1.2",
                "batch_id": "batch-semantic-duplicate",
                "changes": [first_change, second_change],
            },
        )
