"""Production StoryBible output normalization and strict grounding contracts."""

from copy import deepcopy

import pytest

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionContextV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryBibleTrustedEventOrderV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
    derive_storybible_trusted_event_order,
)
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)

CHUNK_TEXT = "Alice met Bob. Alice smiled."


def _ref(
    quote: str | None = "Alice met Bob.",
    *,
    chunk_id: str = "chunk-1",
    start: int | None = None,
    end: int | None = None,
) -> EvidenceRefV1:
    return EvidenceRefV1(
        chunk_id=chunk_id,
        quote_start=start,
        quote_end=end,
        quote_text=quote,
    )


def _context(
    *,
    total_order: bool = True,
    profiles: list[StoryEntityProfileV1] | None = None,
) -> StoryBibleProductionContextV1:
    evidence = _ref()
    chunk = SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=CHUNK_TEXT,
        checksum=checksum_text(CHUNK_TEXT),
    )
    events = [
        EventProposalV1(
            proposal_id=event_id,
            event_type="EVENT",
            summary=event_id,
            evidence_refs=[evidence],
            confidence=0.9,
            reality_layer=RealityLayer.PRIMARY,
        )
        for event_id in ("event-1", "event-2")
    ]
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1",
        source_event_id="event-1",
        target_event_id="event-2",
        relation="BEFORE" if total_order else "UNKNOWN",
        evidence_refs=[evidence] if total_order else [],
        confidence=0.9 if total_order else 0,
    )
    orders = [
        StoryBibleTrustedEventOrderV1(
            event_id="event-1",
            resolved_order=0 if total_order else None,
        ),
        StoryBibleTrustedEventOrderV1(
            event_id="event-2",
            strict_predecessor_event_ids=["event-1"] if total_order else [],
            resolved_order=1 if total_order else None,
        ),
    ]
    snapshot = StoryBibleCanonicalSnapshotV1(
        project_id="project-1",
        profiles=profiles or [],
    )
    return StoryBibleProductionContextV1(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        narrative_analysis_run_id="analysis-1",
        approved_timeline_bundle_id="timeline-1",
        timeline_run_id="timeline-run-1",
        approved_events=events,
        approved_temporal_relations=[relation],
        trusted_event_ids=["event-1", "event-2"],
        trusted_event_order=orders,
        trusted_evidence_refs=[evidence],
        source_chunk_ids=["chunk-1"],
        source_chunks=[chunk],
        canonical_snapshot=snapshot,
        canonical_storybible_snapshot_hash=canonical_storybible_snapshot_hash(snapshot),
    )


def _run(snapshot_hash: str) -> StoryBibleProductionRunV1:
    return StoryBibleProductionRunV1(
        run_id="storybible-run-1",
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=snapshot_hash,
        input_hash="input-hash-1",
        model_identity="model-1",
        status=StoryBibleProductionRunStatus.RESERVED,
    )


def _raw_proposal(
    *,
    alice_id: str = "profile-1",
    bob_id: str = "profile-2",
    fake_hash: str = "fake-hash",
    alice_name: str = "Alice",
) -> StoryBibleCuratorProposalV1:
    evidence = [_ref()]
    alice = ProfileUpdateProposalV1(
        update_id="update-profile-alice",
        project_id="project-1",
        profile=StoryEntityProfileV1(
            profile_id=alice_id,
            project_id="project-1",
            entity_kind="PERSON",
            canonical_name=alice_name,
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    bob = ProfileUpdateProposalV1(
        update_id="update-profile-bob",
        project_id="project-1",
        profile=StoryEntityProfileV1(
            profile_id=bob_id,
            project_id="project-1",
            entity_kind="PERSON",
            canonical_name="Bob",
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    state = StateUpdateProposalV1(
        update_id="update-state",
        project_id="project-1",
        state=StoryEntityStateV1(
            state_id="state-1",
            project_id="project-1",
            profile_id=alice_id,
            state={"mood": "calm"},
            triggering_event_id="event-1",
            valid_from_event_id="event-1",
            valid_from_order=0,
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    relationship = RelationshipUpdateProposalV1(
        update_id="update-relationship",
        project_id="project-1",
        relationship=StoryRelationshipV1(
            relationship_id="relationship-1",
            project_id="project-1",
            source_profile_id=alice_id,
            target_profile_id=bob_id,
            relationship_type="ALLY",
            valid_from_event_id="event-1",
            valid_from_order=0,
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    rule = WorldRuleUpdateProposalV1(
        update_id="update-rule",
        project_id="project-1",
        world_rule=WorldRuleV1(
            rule_id="rule-1",
            project_id="project-1",
            name="Meeting rule",
            statement="Meetings create alliances.",
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    updates = [alice, bob, state, relationship, rule]
    plan = CommitPlanV1(
        commit_plan_id="local-plan",
        project_id="project-1",
        source_proposal_id="local-proposal",
        content_hash=fake_hash,
        updates=updates,
        evidence_refs=evidence,
    )
    return StoryBibleCuratorProposalV1(
        proposal_id="local-proposal",
        project_id="project-1",
        commit_plan=plan,
        conflicts=[
            ConflictV1(
                conflict_id="local-conflict",
                project_id="project-1",
                category="IDENTITY",
                summary="Alice needs review.",
                affected_update_ids=[alice.update_id],
                evidence_refs=evidence,
            )
        ],
        evidence_refs=evidence,
        confidence=0.8,
    )


def _normalize(
    raw: StoryBibleCuratorProposalV1,
    context: StoryBibleProductionContextV1 | None = None,
) -> StoryBibleCuratorProposalV1:
    trusted_context = context or _context()
    return StoryBibleProductionOutputNormalizer().normalize(
        raw,
        context=trusted_context,
        run=_run(trusted_context.canonical_storybible_snapshot_hash),
    )


def _resources(proposal: StoryBibleCuratorProposalV1) -> dict[str, object]:
    result: dict[str, object] = {}
    for update in proposal.commit_plan.updates:
        if isinstance(update, ProfileUpdateProposalV1):
            result[update.profile.canonical_name] = update.profile
        elif isinstance(update, StateUpdateProposalV1):
            result["state"] = update.state
        elif isinstance(update, RelationshipUpdateProposalV1):
            result["relationship"] = update.relationship
        else:
            result["rule"] = update.world_rule
    return result


def test_normalization_is_replay_stable_and_rewrites_complete_graph() -> None:
    first = _normalize(_raw_proposal())
    replay = _normalize(_raw_proposal())
    resources = _resources(first)
    alice = resources["Alice"]
    bob = resources["Bob"]
    state = resources["state"]
    relationship = resources["relationship"]

    assert first == replay
    assert isinstance(alice, StoryEntityProfileV1)
    assert isinstance(bob, StoryEntityProfileV1)
    assert isinstance(state, StoryEntityStateV1)
    assert isinstance(relationship, StoryRelationshipV1)
    assert state.profile_id == alice.profile_id
    assert relationship.source_profile_id == alice.profile_id
    assert relationship.target_profile_id == bob.profile_id
    assert first.conflicts[0].affected_update_ids[0] in {
        update.update_id for update in first.commit_plan.updates
    }
    assert first.evidence_refs[0].quote_start == 0
    assert first.evidence_refs[0].quote_end == 14


def test_server_owned_project_fields_are_rewritten_and_diagnosed() -> None:
    raw = _raw_proposal()
    raw.project_id = "wrong-project"
    raw.commit_plan.project_id = "wrong-project"
    for update in raw.commit_plan.updates:
        update.project_id = "wrong-project"
        resource = update.profile if isinstance(update, ProfileUpdateProposalV1) else None
        if resource is not None:
            resource.project_id = "wrong-project"
        elif isinstance(update, StateUpdateProposalV1):
            update.state.project_id = "wrong-project"
        elif isinstance(update, RelationshipUpdateProposalV1):
            update.relationship.project_id = "wrong-project"
        else:
            assert isinstance(update, WorldRuleUpdateProposalV1)
            update.world_rule.project_id = "wrong-project"
    raw.conflicts[0].project_id = "wrong-project"

    normalizer = StoryBibleProductionOutputNormalizer()
    normalized = normalizer.normalize(
        raw,
        context=_context(),
        run=_run(_context().canonical_storybible_snapshot_hash),
    )

    assert normalized.project_id == "project-1"
    assert normalized.commit_plan.project_id == "project-1"
    assert all(update.project_id == "project-1" for update in normalized.commit_plan.updates)
    resources = _resources(normalized)
    for key in ("Alice", "Bob", "state", "relationship", "rule"):
        resource = resources[key]
        assert isinstance(
            resource,
            (StoryEntityProfileV1, StoryEntityStateV1, StoryRelationshipV1, WorldRuleV1),
        )
        assert resource.project_id == "project-1"
    assert normalized.conflicts[0].project_id == "project-1"
    assert normalizer.last_diagnostics
    assert {item.code for item in normalizer.last_diagnostics} == {"SERVER_FIELD_REWRITTEN"}
    assert all(item.original_value == "<redacted>" for item in normalizer.last_diagnostics)
    assert any(item.field == "commit_plan.project_id" for item in normalizer.last_diagnostics)


def test_semantic_reference_mismatch_is_still_rejected() -> None:
    raw = _raw_proposal()
    state_update = raw.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.profile_id = "missing-profile"

    normalizer = StoryBibleProductionOutputNormalizer()
    with pytest.raises(ValueError, match="unknown profile"):
        normalizer.normalize(
            raw,
            context=_context(),
            run=_run(_context().canonical_storybible_snapshot_hash),
        )
    assert any(
        item.code == "NORMALIZER_CONTRACT_ERROR" for item in normalizer.last_diagnostics
    )
    assert all(item.original_value == "<redacted>" for item in normalizer.last_diagnostics)


def test_new_resource_ids_are_independent_of_arbitrary_local_ids() -> None:
    first = _normalize(_raw_proposal())
    renamed = _raw_proposal(alice_id="arbitrary-a", bob_id="arbitrary-b")
    renamed.commit_plan.updates[2].state.state_id = "arbitrary-state"  # type: ignore[union-attr]
    renamed.commit_plan.updates[3].relationship.relationship_id = (  # type: ignore[union-attr]
        "arbitrary-relationship"
    )
    renamed.commit_plan.updates[4].world_rule.rule_id = "arbitrary-rule"  # type: ignore[union-attr]

    assert _normalize(renamed) == first


def test_exact_existing_canonical_id_is_preserved() -> None:
    canonical = StoryEntityProfileV1(
        profile_id="canonical-alice",
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name="Alice old",
        evidence_refs=[_ref()],
    )
    normalized = _normalize(
        _raw_proposal(alice_id="canonical-alice", alice_name="Alice updated"),
        _context(profiles=[canonical]),
    )

    alice = _resources(normalized)["Alice updated"]
    assert isinstance(alice, StoryEntityProfileV1)
    assert alice.profile_id == "canonical-alice"


def test_duplicate_local_resource_or_update_ids_are_rejected() -> None:
    duplicate_resource = _raw_proposal()
    second_profile = duplicate_resource.commit_plan.updates[1]
    assert isinstance(second_profile, ProfileUpdateProposalV1)
    second_profile.profile.profile_id = "profile-1"
    with pytest.raises(ValueError, match="duplicate local profile_id"):
        _normalize(duplicate_resource)

    duplicate_update = _raw_proposal()
    duplicate_update.commit_plan.updates[1].update_id = "update-profile-alice"
    with pytest.raises(ValueError, match="duplicate local update_id"):
        _normalize(duplicate_update)


def test_dangling_profile_and_unapproved_event_are_rejected() -> None:
    dangling = _raw_proposal()
    state_update = dangling.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.profile_id = "missing-profile"
    with pytest.raises(ValueError, match="unknown profile"):
        _normalize(dangling)

    invented_event = _raw_proposal()
    state_update = invented_event.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.triggering_event_id = "invented-event"
    with pytest.raises(ValueError, match="unapproved event"):
        _normalize(invented_event)


def test_total_and_partial_order_validation_is_conservative() -> None:
    wrong = _raw_proposal()
    state_update = wrong.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.valid_from_order = 1
    with pytest.raises(ValueError, match="does not match trusted event order"):
        _normalize(wrong)

    partial = _raw_proposal()
    state_update = partial.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.valid_from_order = None
    relationship_update = partial.commit_plan.updates[3]
    assert isinstance(relationship_update, RelationshipUpdateProposalV1)
    relationship_update.relationship.valid_from_order = None
    normalized = _normalize(partial, _context(total_order=False))
    normalized_state = _resources(normalized)["state"]
    assert isinstance(normalized_state, StoryEntityStateV1)
    assert normalized_state.valid_from_event_id == "event-1"

    invented_order = deepcopy(partial)
    state_update = invented_order.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.valid_from_order = 0
    with pytest.raises(ValueError, match="not allowed without a trusted total order"):
        _normalize(invented_order, _context(total_order=False))


@pytest.mark.parametrize("relation", ["UNKNOWN", "SIMULTANEOUS", "OVERLAPS"])
def test_non_strict_timeline_relations_never_create_integer_order(relation: str) -> None:
    temporal_relation = TemporalRelationProposalV1(
        proposal_id="relation-nonstrict",
        source_event_id="event-1",
        target_event_id="event-2",
        relation=relation,
        evidence_refs=[] if relation == "UNKNOWN" else [_ref()],
        confidence=0 if relation == "UNKNOWN" else 0.9,
    )

    order = derive_storybible_trusted_event_order(
        ["event-1", "event-2"], [temporal_relation]
    )

    assert [item.resolved_order for item in order] == [None, None]
    assert all(not item.strict_predecessor_event_ids for item in order)


def test_known_reverse_interval_rejected_but_unknown_interval_is_retained() -> None:
    reversed_interval = _raw_proposal()
    state_update = reversed_interval.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.valid_from_event_id = "event-2"
    state_update.state.valid_from_order = 1
    state_update.state.valid_until_event_id = "event-1"
    state_update.state.valid_until_order = 0
    with pytest.raises(ValueError, match="must not precede valid_from_order|reversed"):
        _normalize(reversed_interval)

    unknown = _raw_proposal()
    state_update = unknown.commit_plan.updates[2]
    assert isinstance(state_update, StateUpdateProposalV1)
    state_update.state.valid_from_event_id = "event-2"
    state_update.state.valid_from_order = None
    state_update.state.valid_until_event_id = "event-1"
    state_update.state.valid_until_order = None
    relationship_update = unknown.commit_plan.updates[3]
    assert isinstance(relationship_update, RelationshipUpdateProposalV1)
    relationship_update.relationship.valid_from_order = None
    normalized = _normalize(unknown, _context(total_order=False))
    state = _resources(normalized)["state"]
    assert isinstance(state, StoryEntityStateV1)
    assert state.valid_from_event_id == "event-2"
    assert state.valid_until_event_id == "event-1"


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (EvidenceRefV1(chunk_id="chunk-1"), "exact quote or span"),
        (_ref("missing quote"), "does not match"),
        (_ref("wrong", start=0, end=5), "does not match"),
        (_ref("Alice", start=None, end=None), "ambiguous"),
        (_ref(None, start=0, end=999), "exceeds"),
        (_ref("Alice met Bob.", chunk_id="outside"), "outside trusted"),
    ],
)
def test_strict_evidence_rejects_ungrounded_or_untrusted_refs(
    evidence: EvidenceRefV1, message: str
) -> None:
    raw = _raw_proposal()
    raw.evidence_refs = [evidence]
    with pytest.raises(ValueError, match=message):
        _normalize(raw)


def test_exact_span_and_unambiguous_quote_are_normalized() -> None:
    quote_only = _normalize(_raw_proposal())
    assert quote_only.evidence_refs == [_ref(start=0, end=14)]

    span = _raw_proposal()
    span.evidence_refs = [_ref(None, start=0, end=5)]
    normalized = _normalize(span)
    assert normalized.evidence_refs == [_ref("Alice", start=0, end=5)]


def test_evidence_chunk_project_is_rechecked_at_normalization_boundary() -> None:
    context = _context()
    foreign_chunk = context.source_chunks[0].model_copy(update={"project_id": "project-2"})
    untrusted_context = context.model_copy(update={"source_chunks": [foreign_chunk]})

    with pytest.raises(ValueError, match="belongs to another project"):
        _normalize(_raw_proposal(), untrusted_context)


def test_server_commit_hash_ignores_fake_hash_but_tracks_material_change() -> None:
    first = _normalize(_raw_proposal(fake_hash="fake-one"))
    second = _normalize(_raw_proposal(fake_hash="fake-two"))
    changed = _normalize(_raw_proposal(alice_name="Alicia"))

    assert first.commit_plan.content_hash == second.commit_plan.content_hash
    assert first.commit_plan.content_hash != changed.commit_plan.content_hash


def test_conflict_unknown_or_duplicate_membership_is_rejected() -> None:
    unknown = _raw_proposal()
    unknown.conflicts[0].affected_update_ids = ["missing-update"]
    with pytest.raises(ValueError, match="unknown update_id"):
        _normalize(unknown)

    duplicate = _raw_proposal()
    duplicate.conflicts[0].affected_update_ids = [
        "update-profile-alice",
        "update-profile-alice",
    ]
    with pytest.raises(ValueError, match="duplicate affected_update_ids"):
        _normalize(duplicate)


def test_provider_facing_schema_contains_all_four_update_variants() -> None:
    schema_text = str(StoryBibleCurator._OUTPUT_SCHEMA)

    assert "ProfileUpdateProposalV1" in schema_text
    assert "StateUpdateProposalV1" in schema_text
    assert "RelationshipUpdateProposalV1" in schema_text
    assert "WorldRuleUpdateProposalV1" in schema_text
