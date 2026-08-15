import pytest
from pydantic import ValidationError

from comic_agent.schemas import (
    RelationshipDirectionality,
    RelationshipDomain,
    RelationshipKind,
    RelationshipParticipantKind,
    RelationshipParticipantRefV1,
    RelationshipSignalProposalBatchV1,
    RelationshipSignalProposalV1,
    RelationshipTemporalAnchorV1,
)


def _participant(name: str, kind: str = "CHARACTER") -> dict[str, object]:
    return {
        "mention_text": name,
        "participant_kind": kind,
        "resolution_status": "UNRESOLVED",
        "entity_proposal_id": None,
        "proposal_schema": None,
    }


def _proposal(
    *,
    kind: str = "TRUSTS",
    subject: str = "甲",
    counterpart: str = "乙",
    basis: str = "NARRATED",
    effect: str = "PRESENT",
    support: str = "EXPLICIT",
    speaker: dict[str, object] | None = None,
    context_event: dict[str, object] | None = None,
    temporal: dict[str, object] | None = None,
    evidence: list[dict[str, object]] | None = None,
    directionality: str | None = None,
    proposal_id: str = "relationship-1",
) -> dict[str, object]:
    direction = directionality or (
        "SYMMETRIC"
        if kind
        in {
            "SIBLING_OF",
            "SPOUSE_OF",
            "ROMANTIC_PARTNER_OF",
            "RELATIVE_OF",
            "COOPERATES_WITH",
            "ALLIED_WITH",
            "HOSTILE_TO",
            "RIVALS_WITH",
        }
        else "DIRECTED"
    )
    domain = {
        "PARENT_OF": "KINSHIP",
        "CHILD_OF": "KINSHIP",
        "SIBLING_OF": "KINSHIP",
        "SPOUSE_OF": "KINSHIP",
        "ROMANTIC_PARTNER_OF": "ROMANTIC",
        "RELATIVE_OF": "KINSHIP",
        "MEMBER_OF": "AFFILIATION",
        "LEADS": "HIERARCHY",
        "COMMANDS": "HIERARCHY",
        "REPORTS_TO": "HIERARCHY",
        "MASTER_OF": "HIERARCHY",
        "DISCIPLE_OF": "HIERARCHY",
        "TRUSTS": "TRUST",
        "DISTRUSTS": "TRUST",
        "DEPENDS_ON": "DEPENDENCY",
        "COOPERATES_WITH": "COOPERATION",
        "ALLIED_WITH": "COOPERATION",
        "HOSTILE_TO": "HOSTILITY",
        "RIVALS_WITH": "RIVALRY",
        "PROTECTS": "PROTECTION",
        "THREATENS": "HOSTILITY",
        "DECEIVES": "DECEPTION",
        "BETRAYS": "DECEPTION",
    }.get(kind, "TRUST")
    return {
        "schema_version": "1.0",
        "proposal_id": proposal_id,
        "subject": _participant(subject),
        "counterpart": _participant(
            counterpart,
            "ORGANIZATION"
            if kind in {"MEMBER_OF", "LEADS", "COMMANDS"}
            else "CHARACTER",
        ),
        "relationship_domain": domain,
        "relationship_kind": kind,
        "directionality": direction,
        "signal_effect": effect,
        "assertion_polarity": "DENIED" if effect == "DENIAL" else "AFFIRMED",
        "evidence_basis": basis,
        "support_level": support,
        "source_speaker": speaker,
        "context_event": context_event,
        "temporal_anchor": temporal or {
            "valid_from": None,
            "valid_until": None,
            "anchor_text": None,
            "resolution_status": "UNRESOLVED",
            "event_proposal_id": None,
            "proposal_schema": None,
        },
        "reality_layer": "PRIMARY",
        "evidence_refs": (
            evidence
            if evidence is not None
            else [{"chunk_id": "chunk-1", "quote_text": "甲信任乙"}]
        ),
        "confidence": 0.9,
    }


def _evidence(quote: str, chunk_id: str = "chunk-1") -> dict[str, object]:
    return {"chunk_id": chunk_id, "quote_text": quote}


def _temporal(anchor_text: str | None = None) -> dict[str, object]:
    return {
        "valid_from": None,
        "valid_until": None,
        "anchor_text": anchor_text,
        "resolution_status": "UNRESOLVED",
        "event_proposal_id": None,
        "proposal_schema": None,
    }


def _resolved_participant(
    name: str,
    proposal_id: str,
    kind: str = "CHARACTER",
) -> dict[str, object]:
    return {
        "mention_text": name,
        "participant_kind": kind,
        "resolution_status": "RESOLVED",
        "entity_proposal_id": proposal_id,
        "proposal_schema": "EntityProposalV1",
    }


def _context_event(
    *,
    resolution_status: str = "UNRESOLVED",
    event_proposal_id: str | None = None,
    proposal_schema: str | None = None,
) -> dict[str, object]:
    return {
        "event_summary": "两人交谈",
        "resolution_status": resolution_status,
        "event_proposal_id": event_proposal_id,
        "proposal_schema": proposal_schema,
    }


def test_relationship_signal_core_examples_and_empty_batch() -> None:
    sibling = RelationshipSignalProposalV1.model_validate(
        _proposal(kind="SIBLING_OF", support="EXPLICIT")
    )
    trust = RelationshipSignalProposalV1.model_validate(_proposal())
    member = RelationshipSignalProposalV1.model_validate(_proposal(kind="MEMBER_OF"))
    disciple = RelationshipSignalProposalV1.model_validate(_proposal(kind="DISCIPLE_OF"))
    empty = RelationshipSignalProposalBatchV1(batch_id="empty", signals=[])

    assert sibling.directionality == RelationshipDirectionality.SYMMETRIC
    assert trust.relationship_domain == RelationshipDomain.TRUST
    assert member.counterpart.participant_kind == RelationshipParticipantKind.ORGANIZATION
    assert disciple.relationship_kind == RelationshipKind.DISCIPLE_OF
    assert empty.schema_version == "1.0"


def test_relationship_signal_basis_speaker_and_temporal_rules() -> None:
    speaker = _participant("甲")
    direct = RelationshipSignalProposalV1.model_validate(
        _proposal(basis="DIRECT_STATEMENT", support="LIMITED", speaker=speaker)
    )
    narrated = RelationshipSignalProposalV1.model_validate(_proposal())
    changed = RelationshipSignalProposalV1.model_validate(
        _proposal(
            effect="FORMATION",
            temporal={
                "valid_from": None,
                "valid_until": None,
                "anchor_text": "从那天起",
                "resolution_status": "UNRESOLVED",
                "event_proposal_id": None,
                "proposal_schema": None,
            },
        )
    )

    assert direct.source_speaker is not None
    assert narrated.source_speaker is None
    assert changed.temporal_anchor.anchor_text == "从那天起"

    with pytest.raises(ValidationError, match="source_speaker"):
        RelationshipSignalProposalV1.model_validate(
            _proposal(basis="DIRECT_STATEMENT", support="LIMITED")
        )
    with pytest.raises(ValidationError, match="temporal"):
        RelationshipSignalProposalV1.model_validate(_proposal(effect="FORMATION"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ([_proposal(directionality="SYMMETRIC")], "directionality"),
        (
            [
                _proposal(kind="PARENT_OF", subject="宗门", counterpart="乙")
                | {"subject": _participant("宗门", "ORGANIZATION")}
            ],
            "participant_kind",
        ),
        ([_proposal(subject="甲", counterpart="甲")], "distinct"),
        ([_proposal(effect="DENIAL") | {"assertion_polarity": "AFFIRMED"}], "assertion_polarity"),
        ([_proposal(kind="SIBLING_OF", effect="TERMINATION")], "TERMINATION"),
        (
            [_proposal(basis="INFERRED", evidence=[{"chunk_id": "chunk-1", "quote_text": "线索"}])],
            "two",
        ),
        ([_proposal(effect="UNKNOWN")], "UNKNOWN"),
    ],
)
def test_relationship_signal_rejects_contract_violations(
    changes: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        RelationshipSignalProposalBatchV1.model_validate(
            {"batch_id": "invalid", "signals": changes}
        )


def test_relationship_signal_batch_deduplicates_symmetric_pairs_but_not_directed_reverse() -> None:
    first = _proposal(kind="SIBLING_OF", subject="甲", counterpart="乙", proposal_id="one")
    reverse = _proposal(kind="SIBLING_OF", subject="乙", counterpart="甲", proposal_id="two")
    with pytest.raises(ValidationError, match="semantic duplicate"):
        RelationshipSignalProposalBatchV1.model_validate(
            {"batch_id": "dup", "signals": [first, reverse]}
        )

    directed_a = _proposal(subject="甲", counterpart="乙", proposal_id="one")
    directed_b = _proposal(subject="乙", counterpart="甲", proposal_id="two")
    batch = RelationshipSignalProposalBatchV1.model_validate(
        {"batch_id": "distinct", "signals": [directed_a, directed_b]}
    )
    assert len(batch.signals) == 2


def test_relationship_signal_references_are_source_first_and_strict() -> None:
    unresolved = RelationshipParticipantRefV1.model_validate(_participant("甲"))
    assert unresolved.entity_proposal_id is None
    with pytest.raises(ValidationError, match="UNRESOLVED"):
        RelationshipParticipantRefV1.model_validate(
            _participant("甲")
            | {"entity_proposal_id": "entity-1", "proposal_schema": "EntityProposalV1"}
        )

    with pytest.raises(ValidationError, match="EntityProposalV1"):
        RelationshipParticipantRefV1.model_validate(
            {
                "mention_text": "甲",
                "participant_kind": "CHARACTER",
                "resolution_status": "RESOLVED",
                "entity_proposal_id": "entity-1",
                "proposal_schema": "ClaimProposalV1",
            }
        )


def test_relationship_temporal_anchor_requires_resolution_status() -> None:
    with pytest.raises(ValidationError, match="resolution_status"):
        RelationshipTemporalAnchorV1.model_validate(
            {"valid_from": None, "valid_until": None, "anchor_text": None}
        )


@pytest.mark.parametrize(
    "kind",
    [
        "SIBLING_OF",
        "TRUSTS",
        "MEMBER_OF",
        "DISCIPLE_OF",
        "LEADS",
        "COOPERATES_WITH",
        "HOSTILE_TO",
        "RIVALS_WITH",
        "PROTECTS",
        "DECEIVES",
        "DEPENDS_ON",
    ],
)
def test_each_public_relationship_kind_has_a_valid_proposal(kind: str) -> None:
    proposal = RelationshipSignalProposalV1.model_validate(_proposal(kind=kind))
    assert proposal.relationship_kind == kind


@pytest.mark.parametrize(
    ("basis", "speaker", "support"),
    [
        ("NARRATED", None, "EXPLICIT"),
        ("OBSERVED_ACTION", None, "STRONG"),
        ("DIRECT_STATEMENT", _participant("甲"), "LIMITED"),
        ("REPORTED_STATEMENT", _participant("丙"), "STRONG"),
    ],
)
def test_each_non_inferred_evidence_basis_has_a_valid_shape(
    basis: str, speaker: dict[str, object] | None, support: str
) -> None:
    proposal = RelationshipSignalProposalV1.model_validate(
        _proposal(basis=basis, speaker=speaker, support=support)
    )
    assert proposal.evidence_basis == basis


def test_inferred_requires_two_independent_refs_and_is_limited() -> None:
    proposal = RelationshipSignalProposalV1.model_validate(
        _proposal(
            basis="INFERRED",
            support="LIMITED",
            evidence=[_evidence("线索一"), _evidence("线索二", "chunk-2")],
        )
    )
    assert len(proposal.evidence_refs) == 2


@pytest.mark.parametrize(
    ("kind", "domain"),
    [
        ("SIBLING_OF", "KINSHIP"),
        ("ROMANTIC_PARTNER_OF", "ROMANTIC"),
        ("MEMBER_OF", "AFFILIATION"),
        ("LEADS", "HIERARCHY"),
        ("DEPENDS_ON", "DEPENDENCY"),
        ("TRUSTS", "TRUST"),
        ("COOPERATES_WITH", "COOPERATION"),
        ("HOSTILE_TO", "HOSTILITY"),
        ("RIVALS_WITH", "RIVALRY"),
        ("PROTECTS", "PROTECTION"),
        ("DECEIVES", "DECEPTION"),
    ],
)
def test_every_public_relationship_domain_is_represented_by_a_matching_kind(
    kind: str, domain: str
) -> None:
    proposal = RelationshipSignalProposalV1.model_validate(_proposal(kind=kind))
    assert proposal.relationship_domain == domain


@pytest.mark.parametrize(
    "invalid",
    [
        _proposal(kind="TRUSTS", directionality="SYMMETRIC"),
        _proposal(kind="SIBLING_OF", directionality="DIRECTED"),
        _proposal(kind="PARENT_OF") | {"subject": _participant("宗门", "ORGANIZATION")},
        _proposal(kind="CHILD_OF") | {"counterpart": _participant("宗门", "ORGANIZATION")},
        _proposal(kind="SPOUSE_OF") | {"counterpart": _participant("宗门", "ORGANIZATION")},
        _proposal(kind="MEMBER_OF") | {"subject": _participant("宗门", "ORGANIZATION")},
        _proposal(kind="LEADS") | {"subject": _participant("宗门", "ORGANIZATION")},
    ],
)
def test_relationship_kind_direction_and_participant_matrix_rejects_invalid_inputs(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RelationshipSignalProposalV1.model_validate(invalid)


def test_symmetric_relationship_preserves_source_participant_order() -> None:
    proposal = RelationshipSignalProposalV1.model_validate(
        _proposal(kind="COOPERATES_WITH", subject="乙", counterpart="甲")
    )
    assert proposal.subject.mention_text == "乙"
    assert proposal.counterpart.mention_text == "甲"


@pytest.mark.parametrize(
    "invalid",
    [
        _proposal(basis="NARRATED", speaker=_participant("丙")),
        _proposal(basis="OBSERVED_ACTION", support="EXPLICIT"),
        _proposal(basis="DIRECT_STATEMENT", support="LIMITED"),
        _proposal(basis="DIRECT_STATEMENT", speaker=_participant("甲"), support="EXPLICIT"),
        _proposal(basis="REPORTED_STATEMENT", support="LIMITED"),
        _proposal(basis="REPORTED_STATEMENT", speaker=_participant("丙"), support="EXPLICIT"),
        _proposal(
            basis="INFERRED",
            support="LIMITED",
            speaker=_participant("丙"),
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
        _proposal(
            basis="INFERRED",
            support="STRONG",
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
        _proposal(
            basis="INFERRED",
            support="EXPLICIT",
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
    ],
)
def test_basis_speaker_and_support_contract_rejects_invalid_inputs(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RelationshipSignalProposalV1.model_validate(invalid)


@pytest.mark.parametrize("effect", ["FORMATION", "STRENGTHENING", "WEAKENING", "TERMINATION"])
def test_change_effects_require_non_empty_temporal_anchor_text(effect: str) -> None:
    with pytest.raises(ValidationError, match="temporal anchor_text"):
        RelationshipSignalProposalV1.model_validate(_proposal(effect=effect))

    proposal = RelationshipSignalProposalV1.model_validate(
        _proposal(effect=effect, temporal=_temporal("在那之后"))
    )
    assert proposal.temporal_anchor.valid_from is None
    assert proposal.temporal_anchor.valid_until is None


def test_effect_polarity_and_kinship_termination_rules() -> None:
    present = RelationshipSignalProposalV1.model_validate(_proposal(effect="PRESENT"))
    denial = RelationshipSignalProposalV1.model_validate(_proposal(effect="DENIAL"))
    kinship_denial = RelationshipSignalProposalV1.model_validate(
        _proposal(kind="SIBLING_OF", effect="DENIAL")
    )
    assert present.assertion_polarity == "AFFIRMED"
    assert denial.assertion_polarity == "DENIED"
    assert kinship_denial.signal_effect == "DENIAL"

    invalid_polarities = [
        _proposal(effect="DENIAL") | {"assertion_polarity": "AFFIRMED"},
        _proposal(effect="PRESENT") | {"assertion_polarity": "DENIED"},
        _proposal(kind="SIBLING_OF", effect="TERMINATION", temporal=_temporal("断绝后")),
    ]
    for invalid in invalid_polarities:
        with pytest.raises(ValidationError):
            RelationshipSignalProposalV1.model_validate(invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        _proposal(evidence=[]),
        _proposal(evidence=[_evidence("重复"), _evidence("重复")]),
        _proposal(basis="INFERRED", evidence=[_evidence("只有一条")]),
    ],
)
def test_evidence_contract_rejects_empty_duplicate_or_insufficient_refs(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RelationshipSignalProposalV1.model_validate(invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        _proposal(
            basis="INFERRED",
            effect="FORMATION",
            support="LIMITED",
            temporal=_temporal("形成后"),
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
        _proposal(
            basis="INFERRED",
            effect="STRENGTHENING",
            support="LIMITED",
            temporal=_temporal("增强后"),
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
        _proposal(
            basis="INFERRED",
            effect="WEAKENING",
            support="LIMITED",
            temporal=_temporal("疏远后"),
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
        _proposal(
            basis="INFERRED",
            effect="TERMINATION",
            support="LIMITED",
            temporal=_temporal("终止后"),
            evidence=[_evidence("一"), _evidence("二", "chunk-2")],
        ),
    ],
)
def test_inferred_cannot_claim_relationship_change_effects(invalid: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="INFERRED"):
        RelationshipSignalProposalV1.model_validate(invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        _participant("甲")
        | {"entity_proposal_id": "entity-1"},
        _participant("甲") | {"proposal_schema": "EntityProposalV1"},
        {
            "mention_text": "甲",
            "participant_kind": "CHARACTER",
            "resolution_status": "RESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": "EntityProposalV1",
        },
        {
            "mention_text": "甲",
            "participant_kind": "CHARACTER",
            "resolution_status": "RESOLVED",
            "entity_proposal_id": "entity-1",
            "proposal_schema": None,
        },
        {
            "mention_text": "甲",
            "participant_kind": "CHARACTER",
            "resolution_status": "RESOLVED",
            "entity_proposal_id": "entity-1",
            "proposal_schema": "ClaimProposalV1",
        },
    ],
)
def test_participant_resolution_reference_contract_rejects_invalid_inputs(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RelationshipParticipantRefV1.model_validate(invalid)


def test_resolved_identity_must_not_equal_and_alias_like_mentions_remain_distinct() -> None:
    same_resolved = _proposal() | {
        "subject": _resolved_participant("甲", "entity-1"),
        "counterpart": _resolved_participant("乙", "entity-1"),
    }
    with pytest.raises(ValidationError, match="distinct"):
        RelationshipSignalProposalV1.model_validate(same_resolved)

    different_mentions = RelationshipSignalProposalV1.model_validate(
        _proposal(subject="甲", counterpart="甲君")
    )
    assert different_mentions.subject.mention_text == "甲"
    assert different_mentions.counterpart.mention_text == "甲君"


@pytest.mark.parametrize(
    "invalid",
    [
        _proposal(
            context_event=_context_event(
                resolution_status="RESOLVED",
                event_proposal_id="event-1",
                proposal_schema="ClaimProposalV1",
            )
        ),
        _proposal(
            temporal=_temporal("昨天")
            | {
                "resolution_status": "RESOLVED",
                "event_proposal_id": "event-1",
                "proposal_schema": "ClaimProposalV1",
            }
        ),
    ],
)
def test_resolved_event_references_require_event_proposal_schema(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="EventProposalV1"):
        RelationshipSignalProposalV1.model_validate(invalid)


def test_batch_rejects_duplicate_proposal_ids() -> None:
    first = _proposal(proposal_id="same")
    second = _proposal(counterpart="丙", proposal_id="same")
    with pytest.raises(ValidationError, match="unique proposal_id"):
        RelationshipSignalProposalBatchV1.model_validate(
            {"batch_id": "duplicate-id", "signals": [first, second]}
        )


def test_batch_rejects_exact_semantic_duplicates_ignoring_ids_evidence_order_and_confidence(
) -> None:
    first = _proposal(
        proposal_id="first",
        evidence=[_evidence("甲信任乙"), _evidence("信任", "chunk-2")],
    )
    second = _proposal(
        proposal_id="second",
        evidence=[_evidence("信任", "chunk-2"), _evidence("甲信任乙")],
    ) | {"confidence": 0.2}
    with pytest.raises(ValidationError, match="semantic duplicate"):
        RelationshipSignalProposalBatchV1.model_validate(
            {"batch_id": "semantic-duplicate", "signals": [first, second]}
        )


@pytest.mark.parametrize(
    "modifier",
    [
        {"relationship_kind": "DISTRUSTS", "relationship_domain": "TRUST"},
        {"signal_effect": "WEAKENING", "temporal_anchor": _temporal("后来")},
        {"evidence_basis": "OBSERVED_ACTION", "support_level": "STRONG"},
        {"support_level": "LIMITED"},
        {"source_speaker": _participant("丙")},
        {"context_event": _context_event()},
        {"temporal_anchor": _temporal("次日")},
        {"reality_layer": "DREAM"},
    ],
)
def test_batch_preserves_distinct_semantic_candidates(modifier: dict[str, object]) -> None:
    first = _proposal(proposal_id="first")
    second = _proposal(proposal_id="second") | modifier
    if modifier.get("source_speaker") is not None:
        second["evidence_basis"] = "DIRECT_STATEMENT"
        second["support_level"] = "LIMITED"
    batch = RelationshipSignalProposalBatchV1.model_validate(
        {"batch_id": "distinct-candidates", "signals": [first, second]}
    )
    assert len(batch.signals) == 2


def test_batch_keeps_directed_reverse_and_different_relationship_kinds() -> None:
    directed_reverse = RelationshipSignalProposalBatchV1.model_validate(
        {
            "batch_id": "directed-reverse",
            "signals": [
                _proposal(subject="甲", counterpart="乙", proposal_id="a"),
                _proposal(subject="乙", counterpart="甲", proposal_id="b"),
            ],
        }
    )
    different_kind = RelationshipSignalProposalBatchV1.model_validate(
        {
            "batch_id": "different-kind",
            "signals": [
                _proposal(kind="TRUSTS", proposal_id="a"),
                _proposal(kind="DISTRUSTS", proposal_id="b"),
            ],
        }
    )
    assert len(directed_reverse.signals) == 2
    assert len(different_kind.signals) == 2
