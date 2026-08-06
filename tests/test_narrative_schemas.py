import pytest
from pydantic import ValidationError

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    ActorResolutionStatus,
    ClaimProposalBatchV1,
    ClaimProposalV1,
    ClaimSourceType,
    ClaimTemporalScope,
    ClaimType,
    EntityProposalBatchV1,
    EntityProposalV1,
    EpistemicStatus,
    EventProposalBatchV1,
    EventProposalV1,
    KnowledgeStateProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
    VerificationStatus,
)


def event_payload() -> dict[str, object]:
    return {
        "proposal_id": "proposal-event-1",
        "event_type": "handoff",
        "summary": "陈野把伞递给林夏。",
        "participant_ids": ["char-chen", "char-lin"],
        "location_id": "loc-playground",
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1")],
        "confidence": 0.9,
        "reality_layer": RealityLayer.PRIMARY,
    }


def entity_payload() -> dict[str, object]:
    return {
        "proposal_id": "entity-1",
        "entity_type": "CHARACTER",
        "canonical_name": "林夏",
        "aliases": ["小夏"],
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-entity", quote_text="林夏")],
        "confidence": 0.81,
    }


def test_entity_proposal_batch_minimal_valid_example() -> None:
    batch = EntityProposalBatchV1(
        batch_id="entity-batch-1",
        entities=[
            EntityProposalV1(**entity_payload()),
            EntityProposalV1(
                **(
                    entity_payload()
                    | {
                        "proposal_id": "entity-2",
                        "entity_type": "ORGANIZATION",
                        "canonical_name": "旧馆社",
                        "aliases": [],
                    }
                )
            ),
        ],
    )

    assert batch.schema_version == "1.0"
    assert batch.batch_id == "entity-batch-1"
    assert [entity.proposal_id for entity in batch.entities] == ["entity-1", "entity-2"]


def test_entity_proposal_batch_rejects_empty_entities() -> None:
    with pytest.raises(ValidationError):
        EntityProposalBatchV1(batch_id="entity-batch-1", entities=[])


def test_entity_proposal_batch_rejects_duplicate_entity_ids() -> None:
    with pytest.raises(ValidationError):
        EntityProposalBatchV1(
            batch_id="entity-batch-1",
            entities=[
                EntityProposalV1(**entity_payload()),
                EntityProposalV1(**entity_payload()),
            ],
        )


def test_event_proposal_minimal_valid_example() -> None:
    event = EventProposalV1(**event_payload())

    assert event.proposal_id == "proposal-event-1"
    assert event.evidence_refs[0].chunk_id == "chunk-1"
    assert event.confidence == 0.9
    assert event.actor_resolution_status == ActorResolutionStatus.UNSPECIFIED


def test_event_proposal_batch_minimal_valid_example() -> None:
    batch = EventProposalBatchV1(
        batch_id="event-batch-1",
        events=[
            EventProposalV1(**event_payload()),
            EventProposalV1(**(event_payload() | {"proposal_id": "proposal-event-2"})),
        ],
    )

    assert batch.schema_version == "1.0"
    assert batch.batch_id == "event-batch-1"
    assert [event.proposal_id for event in batch.events] == [
        "proposal-event-1",
        "proposal-event-2",
    ]


def test_event_proposal_batch_requires_events() -> None:
    with pytest.raises(ValidationError):
        EventProposalBatchV1(batch_id="event-batch-1")


def test_event_proposal_batch_rejects_empty_events() -> None:
    with pytest.raises(ValidationError):
        EventProposalBatchV1(batch_id="event-batch-1", events=[])


def test_event_proposal_batch_rejects_duplicate_event_ids() -> None:
    with pytest.raises(ValidationError):
        EventProposalBatchV1(
            batch_id="event-batch-1",
            events=[
                EventProposalV1(**event_payload()),
                EventProposalV1(**event_payload()),
            ],
        )


def test_event_proposal_requires_evidence_refs() -> None:
    payload = event_payload()
    payload.pop("evidence_refs")

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_event_proposal_rejects_empty_evidence_refs() -> None:
    payload = event_payload() | {"evidence_refs": []}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_event_proposal_rejects_confidence_out_of_bounds(confidence: float) -> None:
    payload = event_payload() | {"confidence": confidence}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_event_proposal_rejects_extra_fields() -> None:
    payload = event_payload() | {"canonical_event_id": "event-1"}

    with pytest.raises(ValidationError):
        EventProposalV1(**payload)


def test_event_proposal_known_actor_requires_participants() -> None:
    event = EventProposalV1(
        **(
            event_payload()
            | {"actor_resolution_status": ActorResolutionStatus.KNOWN}
        )
    )

    assert event.actor_resolution_status == ActorResolutionStatus.KNOWN


def test_event_proposal_known_actor_rejects_empty_participants() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(
                event_payload()
                | {
                    "participant_ids": [],
                    "actor_resolution_status": ActorResolutionStatus.KNOWN,
                }
            )
        )


def test_event_proposal_unknown_actor_requires_empty_participants() -> None:
    event = EventProposalV1(
        **(
            event_payload()
            | {
                "participant_ids": [],
                "actor_resolution_status": ActorResolutionStatus.UNKNOWN,
            }
        )
    )

    assert event.actor_resolution_status == ActorResolutionStatus.UNKNOWN
    assert event.participant_ids == []


def test_event_proposal_unknown_actor_rejects_participants() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(event_payload() | {"actor_resolution_status": ActorResolutionStatus.UNKNOWN})
        )


def test_event_proposal_unknown_actor_rejects_unresolved_ref() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(
                event_payload()
                | {
                    "participant_ids": [],
                    "actor_resolution_status": ActorResolutionStatus.UNKNOWN,
                    "unresolved_actor_ref_id": "unresolved-black-glove",
                }
            )
        )


def test_event_proposal_unresolved_actor_accepts_unresolved_ref() -> None:
    event = EventProposalV1(
        **(
            event_payload()
            | {
                "participant_ids": [],
                "actor_resolution_status": ActorResolutionStatus.UNRESOLVED,
                "unresolved_actor_ref_id": "unresolved-gray-coat-person",
            }
        )
    )

    assert event.unresolved_actor_ref_id == "unresolved-gray-coat-person"


def test_event_proposal_unresolved_actor_requires_ref() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(
                event_payload()
                | {
                    "participant_ids": [],
                    "actor_resolution_status": ActorResolutionStatus.UNRESOLVED,
                }
            )
        )


def test_event_proposal_not_applicable_actor_accepts_empty_participants() -> None:
    event = EventProposalV1(
        **(
            event_payload()
            | {
                "participant_ids": [],
                "actor_resolution_status": ActorResolutionStatus.NOT_APPLICABLE,
            }
        )
    )

    assert event.actor_resolution_status == ActorResolutionStatus.NOT_APPLICABLE


def test_event_proposal_not_applicable_actor_rejects_participants() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(
                event_payload()
                | {"actor_resolution_status": ActorResolutionStatus.NOT_APPLICABLE}
            )
        )


def test_event_proposal_unspecified_preserves_legacy_payload() -> None:
    event = EventProposalV1(**(event_payload() | {"participant_ids": []}))

    assert event.actor_resolution_status == ActorResolutionStatus.UNSPECIFIED
    assert event.participant_ids == []


def test_event_proposal_unspecified_rejects_unresolved_ref() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            **(
                event_payload()
                | {
                    "actor_resolution_status": ActorResolutionStatus.UNSPECIFIED,
                    "unresolved_actor_ref_id": "unresolved-someone",
                }
            )
        )


def test_temporal_relation_known_relation_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="BEFORE",
            confidence=0.8,
        )


def test_temporal_relation_unknown_rejects_offset() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="UNKNOWN",
            offset_value=3,
            offset_unit="days",
            confidence=0.5,
        )


def test_temporal_relation_rejects_self_loop() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-temporal-1",
            source_event_id="event-1",
            target_event_id="event-1",
            relation="SIMULTANEOUS",
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
            confidence=0.8,
        )


def test_state_change_proposal_minimal_valid_example() -> None:
    state_change = StateChangeProposalV1(
        proposal_id="proposal-state-1",
        event_id="event-1",
        target_entity_id="char-lin",
        attribute_path="appearance.hair",
        old_value=None,
        new_value="short",
        persistent=True,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
        confidence=0.87,
    )

    assert state_change.target_entity_id == "char-lin"
    assert state_change.evidence_refs[0].chunk_id == "chunk-1"


def claim_payload() -> dict[str, object]:
    return {
        "proposal_id": "claim-1",
        "claim_type": ClaimType.ACCUSATION,
        "claim_text": "林祁说程放拿了门禁卡。",
        "source_type": ClaimSourceType.CHARACTER,
        "source_id": "char-linqi",
        "target_event_id": "event-card-taken",
        "verification_status": VerificationStatus.UNVERIFIED,
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-claim")],
        "confidence": 0.74,
        "reality_layer": RealityLayer.PRIMARY,
        "temporal_scope": ClaimTemporalScope.PAST,
    }


@pytest.mark.parametrize(
    ("claim_type", "temporal_scope"),
    [
        (ClaimType.FACTUAL_ASSERTION, ClaimTemporalScope.PRESENT),
        (ClaimType.BELIEF, ClaimTemporalScope.PRESENT),
        (ClaimType.HYPOTHESIS, ClaimTemporalScope.FUTURE),
        (ClaimType.DENIAL, ClaimTemporalScope.PAST),
        (ClaimType.ACCUSATION, ClaimTemporalScope.PAST),
        (ClaimType.MEMORY, ClaimTemporalScope.PAST),
        (ClaimType.INTERPRETATION, ClaimTemporalScope.PRESENT),
        (ClaimType.EVALUATION, ClaimTemporalScope.PRESENT),
        (ClaimType.PREDICTION, ClaimTemporalScope.FUTURE),
        (ClaimType.COMMITMENT, ClaimTemporalScope.FUTURE),
    ],
)
def test_claim_proposal_v1_2_accepts_current_claim_types(
    claim_type: ClaimType,
    temporal_scope: ClaimTemporalScope,
) -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "proposal_id": f"claim-{claim_type.value.lower()}",
                "claim_type": claim_type,
                "temporal_scope": temporal_scope,
            }
        )
    )

    assert claim.schema_version == "1.2"
    assert claim.claim_type == claim_type
    assert claim.temporal_scope == temporal_scope


def test_claim_proposal_v1_2_accepts_evaluation() -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "schema_version": "1.2",
                "claim_type": "EVALUATION",
                "claim_text": "这门术法的杀伤力惊人。",
                "temporal_scope": ClaimTemporalScope.PRESENT,
            }
        )
    )

    assert claim.schema_version == "1.2"
    assert claim.claim_type == ClaimType.EVALUATION


def test_claim_proposal_v1_1_remains_readable_without_evaluation() -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "schema_version": "1.1",
                "claim_type": "FACTUAL_ASSERTION",
                "temporal_scope": ClaimTemporalScope.PRESENT,
            }
        )
    )

    assert claim.schema_version == "1.1"
    assert claim.claim_type == ClaimType.FACTUAL_ASSERTION


def test_claim_proposal_v1_1_rejects_evaluation() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(
            **(
                claim_payload()
                | {
                    "schema_version": "1.1",
                    "claim_type": "EVALUATION",
                    "temporal_scope": ClaimTemporalScope.PRESENT,
                }
            )
        )


def test_claim_proposal_v1_1_rejects_legacy_assertion() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(
            **(
                claim_payload()
                | {
                    "claim_type": "ASSERTION",
                    "temporal_scope": ClaimTemporalScope.PRESENT,
                }
            )
        )


def test_claim_proposal_v1_1_requires_temporal_scope() -> None:
    payload = claim_payload() | {"schema_version": "1.1"}
    payload.pop("temporal_scope")

    with pytest.raises(ValidationError):
        ClaimProposalV1(**payload)


def test_claim_proposal_v1_0_reads_legacy_assertion_without_temporal_scope() -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "schema_version": "1.0",
                "claim_type": "ASSERTION",
                "temporal_scope": None,
            }
        )
    )

    assert claim.schema_version == "1.0"
    assert claim.claim_type == ClaimType.ASSERTION
    assert claim.temporal_scope is None


def test_claim_proposal_reads_legacy_payload_without_schema_version() -> None:
    payload = claim_payload() | {"claim_type": "ASSERTION"}
    payload.pop("schema_version", None)
    payload.pop("temporal_scope")

    claim = ClaimProposalV1(**payload)

    assert claim.schema_version == "1.0"
    assert claim.claim_type == ClaimType.ASSERTION
    assert claim.temporal_scope is None


def test_claim_proposal_accusation_valid_example() -> None:
    claim = ClaimProposalV1(**claim_payload())

    assert claim.claim_type == ClaimType.ACCUSATION
    assert claim.claim_text == "林祁说程放拿了门禁卡。"
    assert claim.temporal_scope == ClaimTemporalScope.PAST
    assert not isinstance(claim, EventProposalV1)


def test_claim_proposal_batch_minimal_valid_example() -> None:
    batch = ClaimProposalBatchV1(
        batch_id="claim-batch-1",
        claims=[
            ClaimProposalV1(**claim_payload()),
            ClaimProposalV1(
                **(
                    claim_payload()
                    | {
                        "proposal_id": "claim-2",
                        "claim_type": ClaimType.DENIAL,
                        "claim_text": "程放否认自己拿了门禁卡。",
                    }
                )
            ),
        ],
    )

    assert batch.schema_version == "1.2"
    assert batch.batch_id == "claim-batch-1"
    assert [claim.proposal_id for claim in batch.claims] == ["claim-1", "claim-2"]


def test_claim_proposal_batch_v1_1_rejects_legacy_claim_item() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalBatchV1(
            schema_version="1.1",
            batch_id="claim-batch-1",
            claims=[
                ClaimProposalV1(
                    **(
                        claim_payload()
                        | {
                            "schema_version": "1.0",
                            "claim_type": "ASSERTION",
                            "temporal_scope": None,
                        }
                    )
                )
            ],
        )


def test_claim_proposal_batch_v1_0_reads_legacy_claim_items() -> None:
    batch = ClaimProposalBatchV1(
        schema_version="1.0",
        batch_id="claim-batch-legacy-1",
        claims=[
            ClaimProposalV1(
                **(
                    claim_payload()
                    | {
                        "schema_version": "1.0",
                        "claim_type": "ASSERTION",
                        "temporal_scope": None,
                    }
                )
            )
        ],
    )

    assert batch.schema_version == "1.0"
    assert batch.claims[0].claim_type == ClaimType.ASSERTION
    assert batch.claims[0].temporal_scope is None


def test_claim_proposal_batch_reads_legacy_payload_without_schema_version() -> None:
    legacy_claim = claim_payload() | {"claim_type": "ASSERTION"}
    legacy_claim.pop("schema_version", None)
    legacy_claim.pop("temporal_scope")

    batch = ClaimProposalBatchV1(
        batch_id="claim-batch-legacy-1",
        claims=[legacy_claim],
    )

    assert batch.schema_version == "1.0"
    assert batch.claims[0].schema_version == "1.0"
    assert batch.claims[0].claim_type == ClaimType.ASSERTION
    assert batch.claims[0].temporal_scope is None


def test_claim_proposal_batch_rejects_empty_claims() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalBatchV1(batch_id="claim-batch-1", claims=[])


def test_claim_proposal_batch_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalBatchV1(
            batch_id="claim-batch-1",
            claims=[
                ClaimProposalV1(**claim_payload()),
                ClaimProposalV1(**claim_payload()),
            ],
        )


def test_claim_proposal_denial_valid_example() -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "proposal_id": "claim-denial-1",
                "claim_type": ClaimType.DENIAL,
                "claim_text": "程放否认自己拿了门禁卡。",
                "source_id": "char-chengfang",
            }
        )
    )

    assert claim.claim_type == ClaimType.DENIAL


def test_claim_proposal_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"evidence_refs": []}))


@pytest.mark.parametrize("claim_text", ["", "   "])
def test_claim_proposal_rejects_blank_claim_text(claim_text: str) -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"claim_text": claim_text}))


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_claim_proposal_rejects_confidence_out_of_bounds(confidence: float) -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"confidence": confidence}))


def test_claim_proposal_rejects_invalid_claim_type() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"claim_type": "RUMOR"}))


def test_claim_proposal_rejects_invalid_verification_status() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"verification_status": "TRUE"}))


def test_claim_proposal_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(**(claim_payload() | {"canonical_claim_id": "claim-canonical"}))


def test_claim_proposal_unknown_source_accepts_missing_source_id() -> None:
    claim = ClaimProposalV1(
        **(
            claim_payload()
            | {
                "source_type": ClaimSourceType.UNKNOWN,
                "source_id": None,
            }
        )
    )

    assert claim.source_type == ClaimSourceType.UNKNOWN
    assert claim.source_id is None


def test_claim_proposal_unknown_source_rejects_source_id() -> None:
    with pytest.raises(ValidationError):
        ClaimProposalV1(
            **(
                claim_payload()
                | {
                    "source_type": ClaimSourceType.UNKNOWN,
                    "source_id": "char-unknown",
                }
            )
        )


def knowledge_payload() -> dict[str, object]:
    return {
        "proposal_id": "knowledge-1",
        "character_id": "char-shence",
        "knowledge_target_id": "claim-mechanical-door",
        "epistemic_status": EpistemicStatus.HEARD,
        "source_claim_id": "claim-mechanical-door",
        "valid_from_event_id": "event-read-work-order",
        "reality_layer": RealityLayer.PRIMARY,
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-knowledge")],
        "confidence": 0.82,
    }


def test_knowledge_state_proposal_heard_claim_valid_example() -> None:
    knowledge = KnowledgeStateProposalV1(**knowledge_payload())

    assert knowledge.epistemic_status == EpistemicStatus.HEARD
    assert knowledge.source_claim_id == "claim-mechanical-door"


def test_knowledge_state_proposal_knows_target_valid_example() -> None:
    knowledge = KnowledgeStateProposalV1(
        **(
            knowledge_payload()
            | {
                "proposal_id": "knowledge-knows-1",
                "epistemic_status": EpistemicStatus.KNOWS,
                "knowledge_target_id": "fact-backup-door-exists",
                "source_claim_id": None,
            }
        )
    )

    assert knowledge.epistemic_status == EpistemicStatus.KNOWS


def test_knowledge_state_proposal_unaware_reader_visible_boundary_example() -> None:
    knowledge = KnowledgeStateProposalV1(
        **(
            knowledge_payload()
            | {
                "proposal_id": "knowledge-unaware-1",
                "character_id": "char-linqi",
                "knowledge_target_id": "event-black-gloved-hand-took-card",
                "epistemic_status": EpistemicStatus.UNAWARE,
                "source_claim_id": None,
                "valid_from_event_id": "event-reader-visible-card-taking",
            }
        )
    )

    assert knowledge.epistemic_status == EpistemicStatus.UNAWARE


def test_knowledge_state_proposal_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        KnowledgeStateProposalV1(**(knowledge_payload() | {"evidence_refs": []}))


def test_knowledge_state_proposal_rejects_invalid_epistemic_status() -> None:
    with pytest.raises(ValidationError):
        KnowledgeStateProposalV1(**(knowledge_payload() | {"epistemic_status": "SEES"}))


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_knowledge_state_proposal_rejects_confidence_out_of_bounds(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        KnowledgeStateProposalV1(**(knowledge_payload() | {"confidence": confidence}))


def test_knowledge_state_proposal_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeStateProposalV1(
            **(knowledge_payload() | {"visible_to_reader": True})
        )
