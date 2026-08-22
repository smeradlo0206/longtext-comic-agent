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
    CreatureSubtype,
    EntityProposalBatchV1,
    EntityProposalV1,
    EntityType,
    EpistemicBasis,
    EpistemicStatus,
    EventProposalBatchV1,
    EventProposalV1,
    KnowledgeReferenceResolutionStatus,
    KnowledgeStateProposalBatchV1,
    KnowledgeStateProposalV1,
    KnowledgeSubjectRefV1,
    KnowledgeTargetRefV1,
    StateChangeAttributePath,
    StateChangeEventRefV1,
    StateChangeProposalBatchV1,
    StateChangeProposalV1,
    StateChangeTargetKind,
    StateChangeTargetRefV1,
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

    assert batch.schema_version == "1.1"
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


@pytest.mark.parametrize(
    "entity_type",
    [
        EntityType.CHARACTER,
        EntityType.CREATURE,
        EntityType.LOCATION,
        EntityType.ORGANIZATION,
        EntityType.OBJECT,
        EntityType.ABILITY,
        EntityType.CONCEPT,
    ],
)
def test_entity_proposal_v11_accepts_supported_taxonomy(entity_type: EntityType) -> None:
    entity = EntityProposalV1(
        **(
            entity_payload()
            | {
                "schema_version": "1.1",
                "entity_type": entity_type,
                "creature_subtype": (
                    CreatureSubtype.SPIRIT_BEAST if entity_type == EntityType.CREATURE else None
                ),
            }
        )
    )

    assert entity.schema_version == "1.1"
    assert entity.entity_type == entity_type


def test_entity_proposal_v11_rejects_creature_subtype_for_non_creature() -> None:
    with pytest.raises(ValidationError, match="creature_subtype requires entity_type CREATURE"):
        EntityProposalV1(
            **(
                entity_payload()
                | {
                    "schema_version": "1.1",
                    "entity_type": EntityType.CHARACTER,
                    "creature_subtype": CreatureSubtype.MONSTER,
                }
            )
        )


def test_entity_proposal_v10_reads_legacy_entity_without_creature_subtype() -> None:
    entity = EntityProposalV1(
        **(entity_payload() | {"schema_version": "1.0", "entity_type": "PROP"})
    )

    assert entity.schema_version == "1.0"
    assert entity.entity_type == "PROP"
    assert entity.creature_subtype is None


def test_entity_batch_v11_rejects_legacy_entity_items() -> None:
    with pytest.raises(ValidationError, match="v1.1 entity batches require v1.1 entities"):
        EntityProposalBatchV1(
            schema_version="1.1",
            batch_id="entity-batch-v11",
            entities=[EntityProposalV1(**entity_payload() | {"schema_version": "1.0"})],
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

    assert batch.schema_version == "1.1"
    assert batch.batch_id == "event-batch-1"
    assert [event.proposal_id for event in batch.events] == [
        "proposal-event-1",
        "proposal-event-2",
    ]


def test_event_proposal_batch_allows_an_auditable_empty_scope() -> None:
    """A bounded source slice may have no independently supportable event."""

    batch = EventProposalBatchV1(batch_id="event-batch-1", events=[])

    assert batch.schema_version == "1.1"
    assert batch.events == []


def test_event_proposal_batch_reads_legacy_v10_payload() -> None:
    batch = EventProposalBatchV1(
        schema_version="1.0",
        batch_id="event-batch-legacy",
        events=[EventProposalV1(**event_payload())],
    )

    assert batch.schema_version == "1.0"


def test_event_proposal_batch_rejects_duplicate_event_ids() -> None:
    with pytest.raises(ValidationError):
        EventProposalBatchV1(
            batch_id="event-batch-1",
            events=[
                EventProposalV1(**event_payload()),
                EventProposalV1(**event_payload()),
            ],
        )


def test_event_batch_lifts_legacy_outer_version_when_it_contains_v11_mentions() -> None:
    """Provider defaults must not reject otherwise-valid v1.1 mention records."""

    batch = EventProposalBatchV1.model_validate(
        {
            "schema_version": "1.0",
            "batch_id": "event-batch-provider-default",
            "events": [
                event_payload()
                | {
                    "participant_ids": [],
                    "participant_mentions": [
                        {
                            "mention_text": "陈野",
                            "resolution_status": "UNRESOLVED",
                            "proposal_id": None,
                            "proposal_schema": None,
                        }
                    ],
                    "actor_resolution_status": "KNOWN",
                }
            ],
        }
    )

    assert batch.schema_version == "1.1"
    assert batch.events[0].schema_version == "1.1"


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
        **(event_payload() | {"actor_resolution_status": ActorResolutionStatus.KNOWN})
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
            **(event_payload() | {"actor_resolution_status": ActorResolutionStatus.NOT_APPLICABLE})
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
        event={
            "event_summary": "林夏剪短头发。",
            "resolution_status": "UNRESOLVED",
        },
        target={
            "mention_text": "林夏",
            "target_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
        },
        attribute_path="health.injury",
        old_value=None,
        new_value="受伤",
        persistent=True,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
        new_value_evidence_indexes=[0],
        persistence_evidence_indexes=[0],
        confidence=0.87,
    )

    assert state_change.schema_version == "1.3"
    assert state_change.event.event_summary == "林夏剪短头发。"
    assert state_change.target.mention_text == "林夏"
    assert state_change.evidence_refs[0].chunk_id == "chunk-1"


def _state_change_v11_payload() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "proposal_id": "proposal-state-1",
        "event": {
            "event_summary": "林夏剪短头发。",
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "mention_text": "林夏",
            "resolution_status": "UNRESOLVED",
        },
        "attribute_path": "appearance.hair",
        "old_value": "long",
        "new_value": "short",
        "persistent": True,
        "reality_layer": RealityLayer.PRIMARY,
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1", quote_text="林夏剪短头发。")],
        "confidence": 0.87,
    }


def _state_change_v12_payload() -> dict[str, object]:
    return {
        "schema_version": "1.2",
        "proposal_id": "proposal-state-v12-1",
        "event": {
            "event_summary": "林夏被箭射伤。",
            "resolution_status": "UNRESOLVED",
        },
        "target": {
            "mention_text": "林夏",
            "target_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
        },
        "attribute_path": "health.injury",
        "old_value": None,
        "new_value": "受伤",
        "persistent": False,
        "reality_layer": RealityLayer.PRIMARY,
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1", quote_text="林夏被箭射伤。")],
        "new_value_evidence_indexes": [0],
        "persistence_evidence_indexes": [],
        "confidence": 0.87,
    }


def _state_change_v10_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "proposal_id": "proposal-state-legacy-1",
        "event_id": "event-legacy-1",
        "target_entity_id": "entity-legacy-1",
        "attribute_path": "appearance.hair",
        "old_value": "long",
        "new_value": "short",
        "persistent": True,
        "reality_layer": RealityLayer.PRIMARY,
        "evidence_refs": [EvidenceRefV1(chunk_id="chunk-1", quote_text="林夏剪短头发。")],
        "confidence": 0.87,
    }


def test_state_change_v10_reads_explicit_and_unversioned_legacy_payloads() -> None:
    explicit = StateChangeProposalV1.model_validate(_state_change_v10_payload())
    unversioned_payload = _state_change_v10_payload()
    unversioned_payload.pop("schema_version")
    unversioned = StateChangeProposalV1.model_validate(unversioned_payload)

    assert explicit.schema_version == "1.0"
    assert explicit.event_id == "event-legacy-1"
    assert explicit.target_entity_id == "entity-legacy-1"
    assert unversioned.schema_version == "1.0"
    assert unversioned.event_id == "event-legacy-1"
    assert unversioned.target_entity_id == "entity-legacy-1"


def test_state_change_v11_resolved_references_require_candidate_schema_types() -> None:
    state_change = StateChangeProposalV1.model_validate(
        _state_change_v11_payload()
        | {
            "event": {
                "event_summary": "林夏剪短头发。",
                "event_proposal_id": "event-proposal-1",
                "proposal_schema": "EventProposalV1",
                "resolution_status": "RESOLVED",
            },
            "target": {
                "mention_text": "林夏",
                "entity_proposal_id": "entity-proposal-1",
                "proposal_schema": "EntityProposalV1",
                "resolution_status": "RESOLVED",
            },
        }
    )

    assert state_change.event.event_proposal_id == "event-proposal-1"
    assert state_change.target.entity_proposal_id == "entity-proposal-1"


@pytest.mark.parametrize(
    ("reference_model", "payload"),
    [
        (
            StateChangeEventRefV1,
            {
                "event_summary": "门被打开。",
                "event_proposal_id": "event-proposal-1",
                "resolution_status": "UNRESOLVED",
            },
        ),
        (
            StateChangeEventRefV1,
            {
                "event_summary": "门被打开。",
                "resolution_status": "RESOLVED",
            },
        ),
        (
            StateChangeEventRefV1,
            {
                "event_summary": "门被打开。",
                "event_proposal_id": "event-proposal-1",
                "proposal_schema": "ClaimProposalV1",
                "resolution_status": "RESOLVED",
            },
        ),
        (
            StateChangeTargetRefV1,
            {
                "mention_text": "城门",
                "entity_proposal_id": "entity-proposal-1",
                "resolution_status": "UNRESOLVED",
            },
        ),
        (
            StateChangeTargetRefV1,
            {
                "mention_text": "城门",
                "resolution_status": "RESOLVED",
            },
        ),
        (
            StateChangeTargetRefV1,
            {
                "mention_text": "城门",
                "entity_proposal_id": "entity-proposal-1",
                "proposal_schema": "EventProposalV1",
                "resolution_status": "RESOLVED",
            },
        ),
    ],
)
def test_state_change_references_reject_partial_or_wrong_candidate_links(
    reference_model: type[StateChangeEventRefV1] | type[StateChangeTargetRefV1],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        reference_model.model_validate(payload)


@pytest.mark.parametrize("legacy_field", ["event_id", "target_entity_id"])
def test_state_change_v11_rejects_legacy_identifiers(legacy_field: str) -> None:
    with pytest.raises(ValidationError, match="v1.1 cannot include legacy"):
        StateChangeProposalV1.model_validate(
            _state_change_v11_payload()
            | {"schema_version": "1.1", legacy_field: "legacy-id"}
        )


def test_state_change_v11_requires_non_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        StateChangeProposalV1.model_validate(_state_change_v11_payload() | {"evidence_refs": []})


def test_state_change_batch_allows_empty_and_v11_changes() -> None:
    empty_batch = StateChangeProposalBatchV1(
        schema_version="1.1", batch_id="state-batch-empty", changes=[]
    )
    nonempty_batch = StateChangeProposalBatchV1(
        schema_version="1.1",
        batch_id="state-batch-1",
        changes=[StateChangeProposalV1.model_validate(_state_change_v11_payload())],
    )

    assert empty_batch.schema_version == "1.1"
    assert empty_batch.changes == []
    assert nonempty_batch.changes[0].schema_version == "1.1"


def test_state_change_batch_rejects_legacy_and_duplicate_changes() -> None:
    v11_change = StateChangeProposalV1.model_validate(_state_change_v11_payload())
    legacy_change = StateChangeProposalV1.model_validate(_state_change_v10_payload())
    duplicate_id = StateChangeProposalV1.model_validate(_state_change_v11_payload())
    semantic_duplicate = StateChangeProposalV1.model_validate(
        _state_change_v11_payload() | {"proposal_id": "proposal-state-2"}
    )

    with pytest.raises(ValidationError, match="only permits v1.1"):
        StateChangeProposalBatchV1(
            schema_version="1.1", batch_id="state-batch-legacy", changes=[legacy_change]
        )
    with pytest.raises(ValidationError, match="unique proposal_id"):
        StateChangeProposalBatchV1(
            schema_version="1.1",
            batch_id="state-batch-duplicate-id", changes=[v11_change, duplicate_id]
        )
    with pytest.raises(ValidationError, match="semantic duplicate"):
        StateChangeProposalBatchV1(
            schema_version="1.1",
            batch_id="state-batch-semantic-duplicate", changes=[v11_change, semantic_duplicate]
        )


@pytest.mark.parametrize(
    "change",
    [
        _state_change_v11_payload()
        | {
            "proposal_id": "proposal-state-target-2",
            "target": {"mention_text": "城门", "resolution_status": "UNRESOLVED"},
        },
        _state_change_v11_payload()
        | {"proposal_id": "proposal-state-old-2", "old_value": "braided"},
        _state_change_v11_payload()
        | {"proposal_id": "proposal-state-new-2", "new_value": "cut"},
        _state_change_v11_payload()
        | {"proposal_id": "proposal-state-temporary-2", "persistent": False},
        _state_change_v11_payload()
        | {"proposal_id": "proposal-state-flashback-2", "reality_layer": "FLASHBACK"},
        _state_change_v11_payload()
        | {
            "proposal_id": "proposal-state-resolved-2",
            "target": {
                "mention_text": "林夏",
                "entity_proposal_id": "entity-proposal-1",
                "proposal_schema": "EntityProposalV1",
                "resolution_status": "RESOLVED",
            },
        },
    ],
)
def test_state_change_batch_preserves_distinct_semantic_candidates(
    change: dict[str, object],
) -> None:
    batch = StateChangeProposalBatchV1(
        schema_version="1.1",
        batch_id="state-batch-distinct",
        changes=[
            StateChangeProposalV1.model_validate(_state_change_v11_payload()),
            StateChangeProposalV1.model_validate(change),
        ],
    )

    assert len(batch.changes) == 2


@pytest.mark.parametrize(
    ("target_kind", "attribute_path", "new_value"),
    [
        ("CHARACTER", "health.injury", "受伤"),
        ("CHARACTER", "location", "山门"),
        ("OBJECT", "possession.holder", "林夏"),
        ("LOCATION", "accessibility", "封死"),
        ("ORGANIZATION", "availability", "停业"),
    ],
)
def test_state_change_v12_accepts_target_path_compatibility_matrix(
    target_kind: str,
    attribute_path: str,
    new_value: str,
) -> None:
    state_change = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "target": {
                "mention_text": "目标",
                "target_kind": target_kind,
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": attribute_path,
            "new_value": new_value,
        }
    )

    assert state_change.schema_version == "1.2"


@pytest.mark.parametrize(
    ("target_kind", "attribute_path"),
    [
        ("CHARACTER", "accessibility"),
        ("LOCATION", "health.injury"),
        ("OBJECT", "changed"),
        ("OBJECT", ""),
    ],
)
def test_state_change_v12_rejects_incompatible_or_free_form_attribute_paths(
    target_kind: str,
    attribute_path: str,
) -> None:
    with pytest.raises(ValidationError):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {
                "target": {
                    "mention_text": "目标",
                    "target_kind": target_kind,
                    "resolution_status": "UNRESOLVED",
                },
                "attribute_path": attribute_path,
            }
        )


def test_state_change_v12_rejects_event_or_missing_target_kind() -> None:
    with pytest.raises(ValidationError):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {
                "target": {
                    "mention_text": "林夏剪短头发",
                    "target_kind": "EVENT",
                    "resolution_status": "UNRESOLVED",
                }
            }
        )
    with pytest.raises(ValidationError, match="target_kind"):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {"target": {"mention_text": "林夏", "resolution_status": "UNRESOLVED"}}
        )


@pytest.mark.parametrize("old_value", ["未知", "不明", "N/A", "待确认"])
def test_state_change_v12_rejects_placeholder_old_values(old_value: str) -> None:
    with pytest.raises(ValidationError, match="old_value"):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload() | {"old_value": old_value}
        )


@pytest.mark.parametrize("new_value", [None, {"state": "受伤"}, ["受伤"]])
def test_state_change_v12_rejects_missing_or_structured_new_values(new_value: object) -> None:
    with pytest.raises(ValidationError, match="new_value"):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload() | {"new_value": new_value}
        )


@pytest.mark.parametrize(
    "payload",
    [
        _state_change_v12_payload(),
        _state_change_v12_payload()
        | {
            "target": {
                "mention_text": "矿石",
                "target_kind": "OBJECT",
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": "quantity",
            "new_value": 3,
        },
        _state_change_v12_payload()
        | {
            "target": {
                "mention_text": "矿洞入口",
                "target_kind": "LOCATION",
                "resolution_status": "UNRESOLVED",
            },
            "attribute_path": "accessibility",
            "new_value": True,
        },
    ],
)
def test_state_change_v12_accepts_stable_scalar_values(payload: dict[str, object]) -> None:
    assert StateChangeProposalV1.model_validate(payload).new_value is not None


@pytest.mark.parametrize(
    "payload",
    [
        _state_change_v12_payload() | {"evidence_refs": []},
        _state_change_v12_payload() | {"new_value_evidence_indexes": []},
        _state_change_v12_payload() | {"new_value_evidence_indexes": [1]},
        _state_change_v12_payload() | {"new_value_evidence_indexes": [0, 0]},
        _state_change_v12_payload()
        | {"persistent": True, "persistence_evidence_indexes": []},
        _state_change_v12_payload() | {"persistence_evidence_indexes": [0]},
    ],
)
def test_state_change_v12_rejects_invalid_evidence_role_indexes(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StateChangeProposalV1.model_validate(payload)


def test_state_change_v12_requires_new_value_evidence_indexes() -> None:
    payload = _state_change_v12_payload()
    payload.pop("new_value_evidence_indexes")

    with pytest.raises(ValidationError, match="new_value_evidence_indexes"):
        StateChangeProposalV1.model_validate(payload)


def test_state_change_v12_accepts_explicit_persistence_evidence() -> None:
    state_change = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {"persistent": True, "persistence_evidence_indexes": [0]}
    )

    assert state_change.persistence_evidence_indexes == [0]


def test_state_change_v12_batch_defaults_to_v12_and_rejects_older_items() -> None:
    empty_batch = StateChangeProposalBatchV1(
        schema_version="1.2", batch_id="state-batch-v12-empty", changes=[]
    )
    v12_change = StateChangeProposalV1.model_validate(_state_change_v12_payload())
    v11_change = StateChangeProposalV1.model_validate(_state_change_v11_payload())
    v10_change = StateChangeProposalV1.model_validate(_state_change_v10_payload())

    assert empty_batch.schema_version == "1.2"
    with pytest.raises(ValidationError, match="only permits v1.2"):
        StateChangeProposalBatchV1(
            schema_version="1.2", batch_id="state-batch-v12-v11", changes=[v11_change]
        )
    with pytest.raises(ValidationError, match="only permits v1.2"):
        StateChangeProposalBatchV1(
            schema_version="1.2", batch_id="state-batch-v12-v10", changes=[v10_change]
        )
    assert StateChangeProposalBatchV1(
        schema_version="1.2", batch_id="state-batch-v12", changes=[v12_change]
    ).changes == [v12_change]


def test_state_change_v12_batch_rejects_semantic_duplicates_despite_evidence_or_confidence() -> (
    None
):
    first = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "evidence_refs": [
                EvidenceRefV1(chunk_id="chunk-1", quote_text="林夏被箭射伤。"),
                EvidenceRefV1(chunk_id="chunk-2", quote_text="伤势仍未痊愈。"),
            ],
            "new_value_evidence_indexes": [0],
            "confidence": 0.5,
        }
    )
    second = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "proposal_id": "proposal-state-v12-2",
            "evidence_refs": [
                EvidenceRefV1(chunk_id="chunk-2", quote_text="伤势仍未痊愈。"),
                EvidenceRefV1(chunk_id="chunk-1", quote_text="林夏被箭射伤。"),
            ],
            "new_value_evidence_indexes": [1],
            "confidence": 0.9,
        }
    )

    with pytest.raises(ValidationError, match="semantic duplicate"):
        StateChangeProposalBatchV1(
            schema_version="1.2", batch_id="state-batch-v12-duplicate", changes=[first, second]
        )


def test_state_change_v12_batch_allows_distinct_changes_using_the_same_evidence() -> None:
    injury = StateChangeProposalV1.model_validate(_state_change_v12_payload())
    location = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "proposal_id": "proposal-state-v12-location",
            "attribute_path": "location",
            "new_value": "矿洞入口",
        }
    )

    batch = StateChangeProposalBatchV1(
        schema_version="1.2", batch_id="state-batch-v12-distinct", changes=[injury, location]
    )

    assert len(batch.changes) == 2


def test_state_change_v12_public_enums_expose_controlled_values() -> None:
    assert StateChangeTargetKind.CHARACTER == "CHARACTER"
    assert StateChangeTargetKind.OBJECT == "OBJECT"
    assert StateChangeAttributePath.HEALTH_INJURY == "health.injury"
    assert StateChangeAttributePath.ACCESSIBILITY == "accessibility"


def test_state_change_v13_defaults_to_appearance_capable_contract() -> None:
    payload = _state_change_v12_payload() | {
        "schema_version": "1.3",
        "proposal_id": "proposal-state-v13-clothing",
        "attribute_path": "appearance.clothing",
        "old_value": None,
        "new_value": "灰衣",
        "persistent": False,
        "persistence_evidence_indexes": [],
    }

    proposal = StateChangeProposalV1.model_validate(payload)

    assert proposal.schema_version == "1.3"
    assert proposal.attribute_path == "appearance.clothing"


@pytest.mark.parametrize("attribute_path", ["appearance.clothing", "appearance.hairstyle"])
def test_state_change_v13_appearance_paths_accept_character_only(
    attribute_path: str,
) -> None:
    proposal = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "schema_version": "1.3",
            "proposal_id": f"proposal-state-v13-{attribute_path}",
            "attribute_path": attribute_path,
            "new_value": "灰衣" if attribute_path.endswith("clothing") else "长发披下",
        }
    )
    assert proposal.target.target_kind == "CHARACTER"

    with pytest.raises(ValidationError, match="incompatible"):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {
                "schema_version": "1.3",
                "proposal_id": f"proposal-state-v13-object-{attribute_path}",
                "attribute_path": attribute_path,
                "new_value": "灰衣",
                "target": {
                    "mention_text": "衣柜",
                    "target_kind": "OBJECT",
                    "resolution_status": "UNRESOLVED",
                },
            }
        )


@pytest.mark.parametrize(
    "bad_value", ["", "未知", "不明", "N/A", "待确认", {"value": "灰衣"}, ["灰衣"]]
)
def test_state_change_v13_appearance_values_are_constrained(bad_value: object) -> None:
    with pytest.raises(ValidationError):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {
                "schema_version": "1.3",
                "proposal_id": "proposal-state-v13-bad-value",
                "attribute_path": "appearance.clothing",
                "new_value": bad_value,
            }
        )


def test_state_change_v13_batch_accepts_only_v13_items_and_empty_output() -> None:
    empty_batch = StateChangeProposalBatchV1(batch_id="state-batch-v13-empty", changes=[])
    v13_change = StateChangeProposalV1.model_validate(
        _state_change_v12_payload()
        | {
            "schema_version": "1.3",
            "proposal_id": "proposal-state-v13-batch",
            "attribute_path": "appearance.hairstyle",
            "new_value": "长发披下",
        }
    )
    v12_change = StateChangeProposalV1.model_validate(
        _state_change_v12_payload() | {"schema_version": "1.2"}
    )

    assert empty_batch.schema_version == "1.3"
    assert (
        StateChangeProposalBatchV1(
            batch_id="state-batch-v13", changes=[v13_change]
        ).schema_version
        == "1.3"
    )
    with pytest.raises(ValidationError, match="only permits v1.3"):
        StateChangeProposalBatchV1(batch_id="state-batch-v13-v12", changes=[v12_change])


def test_state_change_v12_does_not_accept_v13_appearance_paths() -> None:
    with pytest.raises(ValidationError, match="controlled StateChangeAttributePath"):
        StateChangeProposalV1.model_validate(
            _state_change_v12_payload()
            | {
                "attribute_path": "appearance.clothing",
                "new_value": "灰衣",
            }
        )


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
        KnowledgeStateProposalV1(**(knowledge_payload() | {"visible_to_reader": True}))


def knowledge_v11_payload() -> dict[str, object]:
    return {
        "proposal_id": "knowledge-v11-1",
        "subject": {
            "mention_text": "沈策",
            "entity_proposal_id": "entity-shence",
            "resolution_status": "RESOLVED",
        },
        "target": {
            "target_kind": "CLAIM",
            "target_text": "备用出口存在",
            "proposal_id": "claim-exit",
            "proposal_schema": "ClaimProposalV1",
            "resolution_status": "RESOLVED",
        },
        "epistemic_status": "KNOWS",
        "epistemic_basis": "OBSERVED",
        "valid_from": {
            "anchor_text": "发现维修单后",
            "event_proposal_id": "event-work-order",
            "resolution_status": "RESOLVED",
        },
        "valid_until": None,
        "reality_layer": "PRIMARY",
        "evidence_refs": [{"chunk_id": "chunk-knowledge"}],
        "confidence": 0.82,
    }


def test_knowledge_state_v10_unversioned_payload_remains_readable() -> None:
    knowledge = KnowledgeStateProposalV1.model_validate(knowledge_payload())

    assert knowledge.schema_version == "1.0"
    assert knowledge.character_id == "char-shence"


def test_knowledge_state_v11_resolved_references_are_typed_and_complete() -> None:
    knowledge = KnowledgeStateProposalV1.model_validate(knowledge_v11_payload())

    assert knowledge.schema_version == "1.1"
    assert knowledge.subject.entity_proposal_id == "entity-shence"
    assert knowledge.target.proposal_schema == "ClaimProposalV1"
    assert knowledge.valid_from is not None


def test_knowledge_target_kind_schema_description_defines_cognitive_target_semantics() -> None:
    description = KnowledgeTargetRefV1.model_fields["target_kind"].description

    assert description is not None
    assert "EVENT" in description
    assert "WORLD_FACT" in description
    assert "CLAIM" in description
    assert "cognitive target" in description
    assert "BELIEVES" in description


def test_knowledge_state_v11_accepts_unresolved_source_anchors_without_ids() -> None:
    knowledge = KnowledgeStateProposalV1.model_validate(
        knowledge_v11_payload()
        | {
            "subject": {
                "mention_text": "那名守卫",
                "entity_proposal_id": None,
                "resolution_status": "UNRESOLVED",
            },
            "target": {
                "target_kind": "WORLD_FACT",
                "target_text": "城门在午夜关闭",
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
            "valid_from": {
                "anchor_text": "午夜前",
                "event_proposal_id": None,
                "resolution_status": "UNRESOLVED",
            },
            "epistemic_basis": "UNKNOWN",
        }
    )

    assert knowledge.subject.resolution_status == KnowledgeReferenceResolutionStatus.UNRESOLVED
    assert knowledge.target.proposal_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"mention_text": " ", "entity_proposal_id": None, "resolution_status": "UNRESOLVED"},
        {"mention_text": "沈策", "entity_proposal_id": None, "resolution_status": "RESOLVED"},
        {
            "mention_text": "沈策",
            "entity_proposal_id": "entity-1",
            "resolution_status": "UNRESOLVED",
        },
    ],
)
def test_knowledge_subject_reference_rejects_invalid_resolution_pairing(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        KnowledgeSubjectRefV1.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "target_kind": "CLAIM",
            "target_text": " ",
            "proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        {
            "target_kind": "CLAIM",
            "target_text": "P",
            "proposal_id": "claim-1",
            "proposal_schema": None,
            "resolution_status": "RESOLVED",
        },
        {
            "target_kind": "CLAIM",
            "target_text": "P",
            "proposal_id": "claim-1",
            "proposal_schema": "EventProposalV1",
            "resolution_status": "RESOLVED",
        },
        {
            "target_kind": "UNKNOWN",
            "target_text": "P",
            "proposal_id": "claim-1",
            "proposal_schema": "ClaimProposalV1",
            "resolution_status": "RESOLVED",
        },
    ],
)
def test_knowledge_target_reference_rejects_invalid_resolution_or_schema(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        KnowledgeTargetRefV1.model_validate(payload)


def test_knowledge_state_v11_heard_requires_heard_basis_but_heard_basis_can_support_belief() -> (
    None
):
    with pytest.raises(
        ValidationError, match="HEARD epistemic_status requires HEARD epistemic_basis"
    ):
        KnowledgeStateProposalV1.model_validate(
            knowledge_v11_payload() | {"epistemic_status": "HEARD", "epistemic_basis": "STATED"}
        )

    knowledge = KnowledgeStateProposalV1.model_validate(
        knowledge_v11_payload()
        | {
            "epistemic_status": "BELIEVES",
            "epistemic_basis": "HEARD",
            "target": {
                "target_kind": "WORLD_FACT",
                "target_text": "备用出口存在",
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": "UNRESOLVED",
            },
        }
    )
    assert knowledge.epistemic_basis == EpistemicBasis.HEARD


@pytest.mark.parametrize("epistemic_status", ["BELIEVES", "SUSPECTS", "DISBELIEVES"])
def test_knowledge_state_v11_attitude_statuses_reject_claim_targets(
    epistemic_status: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="BELIEVES, SUSPECTS, and DISBELIEVES must target WORLD_FACT or EVENT",
    ):
        KnowledgeStateProposalV1.model_validate(
            knowledge_v11_payload()
            | {
                "epistemic_status": epistemic_status,
                "epistemic_basis": "STATED",
            }
        )


def test_knowledge_state_v11_rejects_legacy_ids_and_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="v1.1 cannot include legacy"):
        KnowledgeStateProposalV1.model_validate(
            knowledge_v11_payload() | {"schema_version": "1.1", "character_id": "char-old"}
        )
    with pytest.raises(ValidationError):
        KnowledgeStateProposalV1.model_validate(knowledge_v11_payload() | {"evidence_refs": []})


def test_knowledge_state_batch_requires_unique_v11_items() -> None:
    item = KnowledgeStateProposalV1.model_validate(knowledge_v11_payload())
    with pytest.raises(ValidationError, match="unique proposal_id"):
        KnowledgeStateProposalBatchV1(batch_id="knowledge-batch-1", states=[item, item])


def test_knowledge_state_batch_allows_an_empty_successful_result() -> None:
    batch = KnowledgeStateProposalBatchV1(batch_id="knowledge-batch-empty", states=[])

    assert batch.states == []


def test_knowledge_state_batch_nonempty_items_still_require_evidence() -> None:
    with pytest.raises(ValidationError):
        KnowledgeStateProposalBatchV1.model_validate(
            {
                "batch_id": "knowledge-batch-invalid",
                "states": [knowledge_v11_payload() | {"evidence_refs": []}],
            }
        )
