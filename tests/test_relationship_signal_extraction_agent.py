from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.agents.relationship_signal_extraction import (
    RELATIONSHIP_SIGNAL_EXTRACTION_SYSTEM_PROMPT,
    RelationshipSignalExtractionAgent,
)
from comic_agent.schemas import RelationshipSignalProposalBatchV1, SourceChunkV1

_OutputT = TypeVar("_OutputT", bound=BaseModel)


class _FakeProvider:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []
        self.output_models: list[type[BaseModel]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[_OutputT],
    ) -> _OutputT:
        self.requests.append(request)
        self.output_models.append(output_model)
        if isinstance(self.response, BaseModel):
            return self.response  # type: ignore[return-value]
        if not isinstance(self.response, dict):
            return self.response  # type: ignore[return-value]
        return output_model.model_validate(self.response)


def _chunk(chunk_id: str = "chunk-1", text: str = "甲救下乙。") -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=chunk_id,
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text=text,
        checksum="fixture-only",
    )


def _context(*chunks: SourceChunkV1) -> dict[str, object]:
    return {
        "project_id": "project-1",
        "source_chunk_ids": [chunk.chunk_id for chunk in chunks],
        "source_chunks": list(chunks),
    }


def _signal(
    *,
    quote_text: str = "甲救下乙。",
    quote_chunk_id: str = "chunk-1",
    subject: str = "甲",
    counterpart: str = "乙",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "proposal_id": "signal-1",
        "subject": {
            "mention_text": subject,
            "participant_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": None,
        },
        "counterpart": {
            "mention_text": counterpart,
            "participant_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": None,
        },
        "relationship_domain": "PROTECTION",
        "relationship_kind": "PROTECTS",
        "directionality": "DIRECTED",
        "signal_effect": "PRESENT",
        "assertion_polarity": "AFFIRMED",
        "evidence_basis": "NARRATED",
        "support_level": "EXPLICIT",
        "source_speaker": None,
        "context_event": None,
        "temporal_anchor": {
            "valid_from": None,
            "valid_until": None,
            "anchor_text": None,
            "resolution_status": "UNRESOLVED",
            "event_proposal_id": None,
            "proposal_schema": None,
        },
        "reality_layer": "PRIMARY",
        "evidence_refs": [
            {
                "chunk_id": quote_chunk_id,
                "quote_start": None,
                "quote_end": None,
                "quote_text": quote_text,
            }
        ],
        "confidence": 0.9,
    }


def _batch(*signals: dict[str, object]) -> dict[str, object]:
    return {"schema_version": "1.0", "batch_id": "relationship-batch", "signals": signals}


def _semantic_signal(
    *,
    text: str,
    subject: str,
    counterpart: str,
    relationship_domain: str,
    relationship_kind: str,
    directionality: str,
    signal_effect: str = "PRESENT",
    assertion_polarity: str = "AFFIRMED",
    evidence_basis: str = "NARRATED",
    support_level: str = "EXPLICIT",
    counterpart_kind: str = "CHARACTER",
    source_speaker: str | None = None,
    anchor_text: str | None = None,
) -> dict[str, object]:
    """Build one source-grounded v1.0 signal without candidate links."""

    signal = _signal(quote_text=text, subject=subject, counterpart=counterpart)
    signal.update(
        {
            "relationship_domain": relationship_domain,
            "relationship_kind": relationship_kind,
            "directionality": directionality,
            "signal_effect": signal_effect,
            "assertion_polarity": assertion_polarity,
            "evidence_basis": evidence_basis,
            "support_level": support_level,
            "counterpart": {
                "mention_text": counterpart,
                "participant_kind": counterpart_kind,
                "resolution_status": "UNRESOLVED",
                "entity_proposal_id": None,
                "proposal_schema": None,
            },
            "temporal_anchor": {
                "valid_from": None,
                "valid_until": None,
                "anchor_text": anchor_text,
                "resolution_status": "UNRESOLVED",
                "event_proposal_id": None,
                "proposal_schema": None,
            },
        }
    )
    if source_speaker is not None:
        signal["source_speaker"] = {
            "mention_text": source_speaker,
            "participant_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": None,
        }
    return signal


def test_relationship_signal_agent_has_bounded_proposal_only_spec() -> None:
    spec = RelationshipSignalExtractionAgent.spec

    assert spec.agent_id == "relationship-signal-extraction-agent"
    assert spec.reads == ["SourceChunkV1"]
    assert spec.output_schema == "RelationshipSignalProposalBatchV1"
    assert spec.can_write_canonical_data is False
    assert spec.requires_evidence is True
    assert spec.max_context_chunks == 3


def test_relationship_signal_agent_returns_empty_batch_as_success() -> None:
    provider = _FakeProvider(_batch())
    chunk = _chunk()

    result = RelationshipSignalExtractionAgent(provider).run(_context(chunk))

    assert isinstance(result, RelationshipSignalProposalBatchV1)
    assert result.signals == []
    assert provider.output_models == [RelationshipSignalProposalBatchV1]
    assert provider.requests[0]["input_context"] == _context(chunk)


def test_relationship_signal_agent_accepts_source_grounded_unresolved_signal() -> None:
    provider = _FakeProvider(_batch(_signal()))

    result = RelationshipSignalExtractionAgent(provider).run(_context(_chunk()))

    assert result.signals[0].subject.resolution_status == "UNRESOLVED"
    assert result.signals[0].counterpart.resolution_status == "UNRESOLVED"
    assert result.signals[0].evidence_refs[0].quote_text == "甲救下乙。"


def test_relationship_signal_agent_accepts_validated_source_chunk_dicts() -> None:
    chunk = _chunk()
    provider = _FakeProvider(_batch(_signal()))

    result = RelationshipSignalExtractionAgent(provider).run(
        {
            "source_chunk_ids": [chunk.chunk_id],
            "source_chunks": [chunk.model_dump()],
        }
    )

    assert result.signals[0].proposal_id == "signal-1"


@pytest.mark.parametrize(
    ("text", "signal", "expected"),
    [
        (
            "“林昭是林晚的姐姐。”",
            _semantic_signal(
                text="“林昭是林晚的姐姐。”",
                subject="林昭",
                counterpart="林晚",
                relationship_domain="KINSHIP",
                relationship_kind="SIBLING_OF",
                directionality="SYMMETRIC",
            ),
            {
                "relationship_kind": "SIBLING_OF",
                "relationship_domain": "KINSHIP",
                "directionality": "SYMMETRIC",
                "signal_effect": "PRESENT",
                "assertion_polarity": "AFFIRMED",
                "evidence_basis": "NARRATED",
                "support_level": "EXPLICIT",
            },
        ),
        (
            "“顾舟是青崖宗弟子。”",
            _semantic_signal(
                text="“顾舟是青崖宗弟子。”",
                subject="顾舟",
                counterpart="青崖宗",
                counterpart_kind="ORGANIZATION",
                relationship_domain="AFFILIATION",
                relationship_kind="MEMBER_OF",
                directionality="DIRECTED",
            ),
            {"relationship_kind": "MEMBER_OF", "relationship_domain": "AFFILIATION"},
        ),
        (
            "“陆衡拜沈策为师。”",
            _semantic_signal(
                text="“陆衡拜沈策为师。”",
                subject="陆衡",
                counterpart="沈策",
                relationship_domain="HIERARCHY",
                relationship_kind="DISCIPLE_OF",
                directionality="DIRECTED",
                signal_effect="FORMATION",
                anchor_text="拜沈策为师",
            ),
            {
                "relationship_kind": "DISCIPLE_OF",
                "signal_effect": "FORMATION",
                "anchor_text": "拜沈策为师",
            },
        ),
        (
            "“林昭对林晚说：‘我信任你。’”",
            _semantic_signal(
                text="“林昭对林晚说：‘我信任你。’”",
                subject="林昭",
                counterpart="林晚",
                relationship_domain="TRUST",
                relationship_kind="TRUSTS",
                directionality="DIRECTED",
                evidence_basis="DIRECT_STATEMENT",
                support_level="LIMITED",
                source_speaker="林昭",
            ),
            {
                "relationship_kind": "TRUSTS",
                "evidence_basis": "DIRECT_STATEMENT",
                "support_level": "LIMITED",
                "speaker": "林昭",
            },
        ),
        (
            "“箭雨落下时，顾舟挡在林晚身前，替她承受了攻击。”",
            _semantic_signal(
                text="“箭雨落下时，顾舟挡在林晚身前，替她承受了攻击。”",
                subject="顾舟",
                counterpart="林晚",
                relationship_domain="PROTECTION",
                relationship_kind="PROTECTS",
                directionality="DIRECTED",
                evidence_basis="OBSERVED_ACTION",
                support_level="STRONG",
            ),
            {
                "relationship_kind": "PROTECTS",
                "evidence_basis": "OBSERVED_ACTION",
                "support_level": "STRONG",
            },
        ),
        (
            "“顾舟当众否认自己与青崖宗结盟。”",
            _semantic_signal(
                text="“顾舟当众否认自己与青崖宗结盟。”",
                subject="顾舟",
                counterpart="青崖宗",
                counterpart_kind="ORGANIZATION",
                relationship_domain="COOPERATION",
                relationship_kind="ALLIED_WITH",
                directionality="SYMMETRIC",
                signal_effect="DENIAL",
                assertion_polarity="DENIED",
                evidence_basis="DIRECT_STATEMENT",
                support_level="LIMITED",
                source_speaker="顾舟",
            ),
            {
                "relationship_kind": "ALLIED_WITH",
                "signal_effect": "DENIAL",
                "assertion_polarity": "DENIED",
                "speaker": "顾舟",
            },
        ),
        (
            "“从那天起，林昭不再信任林晚。”",
            _semantic_signal(
                text="“从那天起，林昭不再信任林晚。”",
                subject="林昭",
                counterpart="林晚",
                relationship_domain="TRUST",
                relationship_kind="DISTRUSTS",
                directionality="DIRECTED",
                signal_effect="FORMATION",
                anchor_text="从那天起",
            ),
            {
                "relationship_kind": "DISTRUSTS",
                "signal_effect": "FORMATION",
                "anchor_text": "从那天起",
            },
        ),
    ],
)
def test_relationship_signal_agent_accepts_semantic_positive_cases(
    text: str,
    signal: dict[str, object],
    expected: dict[str, str],
) -> None:
    result = RelationshipSignalExtractionAgent(_FakeProvider(_batch(signal))).run(
        _context(_chunk(text=text))
    )

    assert len(result.signals) == 1
    actual = result.signals[0]
    for field_name, expected_value in expected.items():
        if field_name == "anchor_text":
            assert actual.temporal_anchor.anchor_text == expected_value
        elif field_name == "speaker":
            assert actual.source_speaker is not None
            assert actual.source_speaker.mention_text == expected_value
        else:
            assert getattr(actual, field_name) == expected_value
    assert actual.subject.resolution_status == "UNRESOLVED"
    assert actual.counterpart.resolution_status == "UNRESOLVED"
    assert actual.temporal_anchor.resolution_status == "UNRESOLVED"
    assert actual.subject.entity_proposal_id is None
    assert actual.counterpart.entity_proposal_id is None
    assert actual.evidence_refs[0].chunk_id == "chunk-1"
    assert actual.evidence_refs[0].quote_text == text


@pytest.mark.parametrize(
    "text",
    [
        "“林昭在门口看见了林晚。”",
        "“林昭向林晚问路，林晚指了指东边。”",
        "“林昭把钥匙递给林晚。”",
        "“林昭与林晚为一盏灯争吵了几句。”",
        "“林昭怀疑林晚隐瞒了真相。”",
        "“林昭说：‘林晚是叛徒。’”",
    ],
)
def test_relationship_signal_agent_accepts_empty_batch_for_non_relationship_semantics(
    text: str,
) -> None:
    result = RelationshipSignalExtractionAgent(_FakeProvider(_batch())).run(
        _context(_chunk(text=text))
    )

    assert result.schema_version == "1.0"
    assert result.signals == []


def test_relationship_signal_agent_keeps_limited_protection_without_upgrading_it() -> None:
    text = "“顾舟救下林晚。”"
    protects = _semantic_signal(
        text=text,
        subject="顾舟",
        counterpart="林晚",
        relationship_domain="PROTECTION",
        relationship_kind="PROTECTS",
        directionality="DIRECTED",
        evidence_basis="OBSERVED_ACTION",
        support_level="LIMITED",
    )

    result = RelationshipSignalExtractionAgent(_FakeProvider(_batch(protects))).run(
        _context(_chunk(text=text))
    )

    assert [signal.relationship_kind for signal in result.signals] == ["PROTECTS"]
    assert {signal.relationship_kind for signal in result.signals}.isdisjoint(
        {"ALLIED_WITH", "TRUSTS", "COOPERATES_WITH"}
    )


def test_relationship_signal_agent_rejects_traitor_label_as_binary_betrayal() -> None:
    """A statement calling someone a traitor is a Claim, not a BETRAYS relation."""

    text = "林昭说：‘林晚是叛徒。’"
    response = _batch(
        _semantic_signal(
            text=text,
            subject="林晚",
            counterpart="林昭",
            relationship_domain="DECEPTION",
            relationship_kind="BETRAYS",
            directionality="DIRECTED",
            evidence_basis="DIRECT_STATEMENT",
            support_level="LIMITED",
            source_speaker="林昭",
        )
    )

    with pytest.raises(ValueError, match="traitor label.*Claim"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(
            _context(_chunk(text=text))
        )


@pytest.mark.parametrize(
    ("response", "context", "error"),
    [
        (_batch(_signal(quote_chunk_id="chunk-2")), _context(_chunk()), "evidence must reference"),
        (_batch(_signal(quote_text="不存在。")), _context(_chunk()), "quote_text must be verbatim"),
        (_batch(_signal(subject="丙")), _context(_chunk()), "subject mention_text must appear"),
        (
            _batch(_signal(counterpart="丙")),
            _context(_chunk()),
            "counterpart mention_text must appear",
        ),
    ],
)
def test_relationship_signal_agent_rejects_source_boundary_violations(
    response: dict[str, object], context: dict[str, object], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(context)


def test_relationship_signal_agent_rejects_inexact_evidence_offsets() -> None:
    response = _batch(_signal())
    response["signals"][0]["evidence_refs"][0].update(  # type: ignore[index]
        {"quote_start": 0, "quote_end": 4}
    )

    with pytest.raises(ValueError, match="offsets must exactly match"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_out_of_range_evidence_offsets() -> None:
    response = _batch(_signal())
    response["signals"][0]["evidence_refs"][0].update(  # type: ignore[index]
        {"quote_start": 0, "quote_end": 999}
    )

    with pytest.raises(ValueError, match="offsets must be within source chunk bounds"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_unpaired_evidence_offsets() -> None:
    response = _batch(_signal())
    response["signals"][0]["evidence_refs"][0]["quote_start"] = 0  # type: ignore[index]

    with pytest.raises(ValidationError, match="quote_start and quote_end"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_resolved_candidate_links() -> None:
    response = _batch(_signal())
    response["signals"][0]["subject"].update(  # type: ignore[index]
        {
            "resolution_status": "RESOLVED",
            "entity_proposal_id": "entity-proposal-1",
            "proposal_schema": "EntityProposalV1",
        }
    )

    with pytest.raises(ValueError, match="requires UNRESOLVED"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


@pytest.mark.parametrize("reference_name", ["context_event", "temporal_anchor"])
def test_relationship_signal_agent_rejects_resolved_event_candidate_links(
    reference_name: str,
) -> None:
    response = _batch(_signal())
    resolved_event = {
        "resolution_status": "RESOLVED",
        "event_proposal_id": "event-proposal-1",
        "proposal_schema": "EventProposalV1",
    }
    if reference_name == "context_event":
        response["signals"][0][reference_name] = {  # type: ignore[index]
            "event_summary": "甲救下乙。",
            **resolved_event,
        }
    else:
        response["signals"][0][reference_name].update(resolved_event)  # type: ignore[index]

    with pytest.raises(ValueError, match=f"UNRESOLVED {reference_name}"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_absent_unresolved_speaker_mention() -> None:
    response = _batch(_signal(quote_text="甲说乙信任甲。", subject="乙", counterpart="甲"))
    response["signals"][0].update(  # type: ignore[index]
        {
            "relationship_domain": "TRUST",
            "relationship_kind": "TRUSTS",
            "evidence_basis": "DIRECT_STATEMENT",
            "support_level": "LIMITED",
            "source_speaker": {
                "mention_text": "丙",
                "participant_kind": "CHARACTER",
                "resolution_status": "UNRESOLVED",
                "entity_proposal_id": None,
                "proposal_schema": None,
            },
        }
    )

    with pytest.raises(ValueError, match="source_speaker mention_text must appear"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(
            _context(_chunk(text="甲说乙信任甲。"))
        )


def test_relationship_signal_agent_rejects_inferred_basis() -> None:
    response = _batch(_signal(quote_text="甲救下乙。甲站在乙前。"))
    response["signals"][0].update(  # type: ignore[index]
        {
            "evidence_basis": "INFERRED",
            "support_level": "LIMITED",
            "evidence_refs": [
                {"chunk_id": "chunk-1", "quote_text": "甲救下乙。"},
                {"chunk_id": "chunk-1", "quote_text": "甲站在乙前。"},
            ],
        }
    )

    with pytest.raises(ValueError, match="does not allow INFERRED"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(
            _context(_chunk(text="甲救下乙。甲站在乙前。"))
        )


@pytest.mark.parametrize("wrong_collection", ["states", "changes", "events"])
def test_relationship_signal_agent_rejects_wrong_batch_collection_fields(
    wrong_collection: str,
) -> None:
    with pytest.raises(ValidationError):
        RelationshipSignalExtractionAgent(
            _FakeProvider({"schema_version": "1.0", "batch_id": "wrong", wrong_collection: []})
        ).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_source_chunk_id_and_payload_mismatch() -> None:
    first = _chunk("chunk-1")
    second = _chunk("chunk-2", "乙离开。")

    with pytest.raises(ValueError, match="must exactly match supplied"):
        RelationshipSignalExtractionAgent(_FakeProvider(_batch())).run(
            {"source_chunk_ids": [first.chunk_id], "source_chunks": [first, second]}
        )


def test_relationship_signal_agent_rejects_evidence_id_present_only_in_declared_ids() -> None:
    response = _batch(_signal(quote_chunk_id="chunk-2"))
    first = _chunk("chunk-1")

    with pytest.raises(ValueError, match="must exactly match supplied"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(
            {"source_chunk_ids": ["chunk-1", "chunk-2"], "source_chunks": [first]}
        )


def test_relationship_signal_agent_rejects_quote_end_without_quote_start() -> None:
    response = _batch(_signal())
    response["signals"][0]["evidence_refs"][0]["quote_end"] = 4  # type: ignore[index]

    with pytest.raises(ValidationError, match="quote_start and quote_end"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_source_speaker_candidate_link() -> None:
    text = "“林昭对林晚说：‘我信任你。’”"
    response = _batch(
        _semantic_signal(
            text=text,
            subject="林昭",
            counterpart="林晚",
            relationship_domain="TRUST",
            relationship_kind="TRUSTS",
            directionality="DIRECTED",
            evidence_basis="DIRECT_STATEMENT",
            support_level="LIMITED",
            source_speaker="林昭",
        )
    )
    response["signals"][0]["source_speaker"].update(  # type: ignore[index]
        {
            "resolution_status": "RESOLVED",
            "entity_proposal_id": "entity-1",
            "proposal_schema": "EntityProposalV1",
        }
    )

    with pytest.raises(ValueError, match="UNRESOLVED source_speaker"):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(_context(_chunk(text=text)))


def test_relationship_signal_agent_rejects_non_batch_provider_result() -> None:
    with pytest.raises(ValueError, match="must return RelationshipSignalProposalBatchV1"):
        RelationshipSignalExtractionAgent(_FakeProvider("not-json")).run(_context(_chunk()))


def test_relationship_signal_agent_rejects_single_proposal_instead_of_batch() -> None:
    with pytest.raises(ValidationError, match="batch_id"):
        RelationshipSignalExtractionAgent(_FakeProvider(_signal())).run(_context(_chunk()))


@pytest.mark.parametrize(
    ("response", "schema_message"),
    [
        (_batch(_signal(subject="甲", counterpart="甲")), "distinct"),
        (
            _batch(
                _semantic_signal(
                    text="“林昭信任林晚。”",
                    subject="林昭",
                    counterpart="林晚",
                    relationship_domain="TRUST",
                    relationship_kind="TRUSTS",
                    directionality="DIRECTED",
                    evidence_basis="DIRECT_STATEMENT",
                    support_level="LIMITED",
                )
            ),
            "source_speaker",
        ),
        (
            _batch(
                _semantic_signal(
                    text="“林昭信任林晚。”",
                    subject="林昭",
                    counterpart="林晚",
                    relationship_domain="TRUST",
                    relationship_kind="TRUSTS",
                    directionality="DIRECTED",
                    source_speaker="林昭",
                )
            ),
            "forbids source_speaker",
        ),
        (
            _batch(
                _semantic_signal(
                    text="“顾舟挡在林晚身前。”",
                    subject="顾舟",
                    counterpart="林晚",
                    relationship_domain="PROTECTION",
                    relationship_kind="PROTECTS",
                    directionality="DIRECTED",
                    evidence_basis="OBSERVED_ACTION",
                    support_level="EXPLICIT",
                )
            ),
            "OBSERVED_ACTION",
        ),
        (
            _batch(
                _semantic_signal(
                    text="“林昭不再信任林晚。”",
                    subject="林昭",
                    counterpart="林晚",
                    relationship_domain="TRUST",
                    relationship_kind="TRUSTS",
                    directionality="DIRECTED",
                    signal_effect="WEAKENING",
                )
            ),
            "temporal anchor_text",
        ),
        (
            _batch(
                _semantic_signal(
                    text="“林昭是林晚的姐姐。”",
                    subject="林昭",
                    counterpart="林晚",
                    relationship_domain="KINSHIP",
                    relationship_kind="SIBLING_OF",
                    directionality="DIRECTED",
                )
            ),
            "directionality",
        ),
    ],
)
def test_relationship_signal_agent_propagates_schema_semantic_rejections(
    response: dict[str, object],
    schema_message: str,
) -> None:
    """These fail in Batch Pydantic validation before the source-only guard executes."""

    with pytest.raises(ValidationError, match=schema_message):
        RelationshipSignalExtractionAgent(_FakeProvider(response)).run(
            _context(_chunk(text="“林昭信任林晚。”顾舟挡在林晚身前。林昭不再信任林晚。"))
        )


def test_relationship_signal_prompt_declares_required_boundaries() -> None:
    prompt = " ".join(RELATIONSHIP_SIGNAL_EXTRACTION_SYSTEM_PROMPT.split())

    for required_text in (
        "RelationshipSignalProposalBatchV1",
        "signals=[]",
        "UNRESOLVED",
        "never invent",
        "INFERRED",
        "EntityProposalV1",
        "EventProposalV1",
        "ClaimProposalV1",
        "KnowledgeStateProposalV1",
        "StateChangeProposalV1",
        "quote_start",
        "exclusive end",
        "StoryBible",
        "final JSON only",
        "confirmed or permanent relationship fact",
        "Ordinary co-presence",
        "single normal exchange",
        "never alone implies ALLIED_WITH, COOPERATES_WITH, TRUSTS",
        "never alone means RIVALS_WITH",
        "Entity extraction identifies existence",
        "Event extraction records what happened",
        "KnowledgeStateProposalV1 records knowing",
        "StateChangeProposalV1 records persistent target attributes",
        "traitor label is a Claim, not a binary BETRAYS relation",
        "no longer trusts means DISTRUSTS plus FORMATION",
        "DIRECT_STATEMENT and REPORTED_STATEMENT require source_speaker",
        "OBSERVED_ACTION never uses EXPLICIT",
        "Do not output INFERRED",
        "temporal_anchor.anchor_text",
        "Do not expand \"他\", \"她\"",
        "Default quote_start and quote_end to null",
        "Python half-open",
    ):
        assert required_text in prompt
    assert "Only NARRATED may use EXPLICIT" in prompt
    assert "states=[]" not in prompt
    assert "changes=[]" not in prompt
