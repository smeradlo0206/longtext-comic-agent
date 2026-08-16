"""Consuming timeline relation output to stamp state intervals."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import TemporalRelation, TemporalRelationProposalV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleUpdateV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)
from comic_agent.services.storybible_event_order import (
    apply_event_orders_to_plan,
    assign_event_orders,
)


def relation(
    source: str,
    target: str,
    relation_label: TemporalRelation,
) -> TemporalRelationProposalV1:
    return TemporalRelationProposalV1(
        proposal_id=f"rel-{source}-{target}",
        source_event_id=source,
        target_event_id=target,
        relation=relation_label,
        evidence_refs=(
            []
            if relation_label == TemporalRelation.UNKNOWN
            else [EvidenceRefV1(chunk_id="c")]
        ),
        confidence=0.9,
    )


def test_before_chain_assigns_increasing_orders() -> None:
    relations = [
        relation("e1", "e2", TemporalRelation.BEFORE),
        relation("e2", "e3", TemporalRelation.BEFORE),
    ]
    assert assign_event_orders(relations) == {"e1": 0, "e2": 1, "e3": 2}


def test_after_relation_orders_in_reverse_direction() -> None:
    assert assign_event_orders([relation("e2", "e1", TemporalRelation.AFTER)]) == {
        "e1": 0,
        "e2": 1,
    }


def test_non_ordering_relations_impose_no_order() -> None:
    relations = [
        relation("e1", "e2", TemporalRelation.SIMULTANEOUS),
        relation("e1", "e3", TemporalRelation.OVERLAPS),
        relation("e1", "e4", TemporalRelation.DURING),
        relation("e1", "e5", TemporalRelation.CONTAINS),
        relation("e1", "e6", TemporalRelation.UNKNOWN),
    ]
    assert assign_event_orders(relations) == {}


def test_unknown_only_timeline_output_stamps_nothing() -> None:
    """A RULES_ONLY timeline analysis must never fabricate sequence numbers."""

    relations = [
        relation("e1", "e2", TemporalRelation.UNKNOWN),
        relation("e2", "e3", TemporalRelation.UNKNOWN),
    ]
    assert assign_event_orders(relations) == {}


def test_cycles_receive_no_order() -> None:
    relations = [
        relation("e1", "e2", TemporalRelation.BEFORE),
        relation("e2", "e1", TemporalRelation.BEFORE),
    ]
    assert assign_event_orders(relations) == {}


def test_single_edge_assigns_the_two_endpoints() -> None:
    relations = [relation("e1", "e2", TemporalRelation.BEFORE)]
    assert assign_event_orders(relations) == {"e1": 0, "e2": 1}


def test_assignment_is_deterministic_across_relation_order() -> None:
    first = [
        relation("e1", "e3", TemporalRelation.BEFORE),
        relation("e2", "e3", TemporalRelation.BEFORE),
    ]
    second = [
        relation("e2", "e3", TemporalRelation.BEFORE),
        relation("e1", "e3", TemporalRelation.BEFORE),
    ]
    expected = {"e1": 0, "e2": 0, "e3": 1}
    assert assign_event_orders(first) == expected
    assert assign_event_orders(second) == expected


def state_update(
    *,
    state_id: str = "state-a",
    from_event_id: str | None = None,
    until_event_id: str | None = None,
    triggering_event_id: str | None = None,
    valid_from_order: int | None = None,
    valid_until_order: int | None = None,
) -> StateUpdateProposalV1:
    evidence = [EvidenceRefV1(chunk_id="c")]
    return StateUpdateProposalV1(
        update_id=f"update-{state_id}",
        project_id="project-a",
        state=StoryEntityStateV1(
            state_id=state_id,
            project_id="project-a",
            profile_id="profile-a",
            state={"location": "market"},
            triggering_event_id=triggering_event_id,
            valid_from_event_id=from_event_id,
            valid_until_event_id=until_event_id,
            valid_from_order=valid_from_order,
            valid_until_order=valid_until_order,
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )


def plan_with(*updates: StoryBibleUpdateV1) -> CommitPlanV1:
    evidence = [EvidenceRefV1(chunk_id="c")]
    return CommitPlanV1(
        commit_plan_id="plan-a",
        project_id="project-a",
        source_proposal_id="proposal-a",
        updates=list(updates),
        evidence_refs=evidence,
    )


def test_stamps_state_orders_from_provided_event_orders() -> None:
    plan = plan_with(state_update(state_id="state-a", from_event_id="e2", until_event_id="e4"))
    stamped = apply_event_orders_to_plan(plan, {"e2": 1, "e4": 3})
    stamped_state = stamped.updates[0]
    assert isinstance(stamped_state, StateUpdateProposalV1)
    assert stamped_state.state.valid_from_order == 1
    assert stamped_state.state.valid_until_order == 2


def test_uses_the_triggering_event_as_the_from_anchor() -> None:
    plan = plan_with(state_update(state_id="state-a", triggering_event_id="e2"))
    stamped = apply_event_orders_to_plan(plan, {"e2": 4})
    stamped_state = stamped.updates[0]
    assert isinstance(stamped_state, StateUpdateProposalV1)
    assert stamped_state.state.valid_from_order == 4


def test_preserves_existing_order_values() -> None:
    plan = plan_with(state_update(state_id="state-a", from_event_id="e2", valid_from_order=7))
    stamped = apply_event_orders_to_plan(plan, {"e2": 1})
    stamped_state = stamped.updates[0]
    assert isinstance(stamped_state, StateUpdateProposalV1)
    assert stamped_state.state.valid_from_order == 7


def test_drops_an_until_order_that_would_invert_the_interval() -> None:
    plan = plan_with(state_update(state_id="state-a", from_event_id="e2", until_event_id="e3"))
    stamped = apply_event_orders_to_plan(plan, {"e2": 5, "e3": 5})
    stamped_state = stamped.updates[0]
    assert isinstance(stamped_state, StateUpdateProposalV1)
    assert stamped_state.state.valid_from_order == 5
    assert stamped_state.state.valid_until_order is None


def test_leaves_until_unset_when_the_until_event_is_order_zero() -> None:
    plan = plan_with(state_update(state_id="state-a", until_event_id="e0"))
    stamped = apply_event_orders_to_plan(plan, {"e0": 0})
    stamped_state = stamped.updates[0]
    assert isinstance(stamped_state, StateUpdateProposalV1)
    assert stamped_state.state.valid_until_order is None


def test_stamps_relationship_orders() -> None:
    evidence = [EvidenceRefV1(chunk_id="c")]
    update = RelationshipUpdateProposalV1(
        update_id="update-rel",
        project_id="project-a",
        relationship=StoryRelationshipV1(
            relationship_id="rel-a",
            project_id="project-a",
            source_profile_id="profile-a",
            target_profile_id="profile-b",
            relationship_type="ALLY",
            valid_from_event_id="e2",
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    stamped = apply_event_orders_to_plan(plan_with(update), {"e2": 2})
    stamped_update = stamped.updates[0]
    assert isinstance(stamped_update, RelationshipUpdateProposalV1)
    assert stamped_update.relationship.valid_from_order == 2


def test_leaves_other_update_kinds_untouched() -> None:
    evidence = [EvidenceRefV1(chunk_id="c")]
    rule_update = WorldRuleUpdateProposalV1(
        update_id="update-rule",
        project_id="project-a",
        world_rule=WorldRuleV1(
            rule_id="rule-a",
            project_id="project-a",
            name="gravity",
            statement="Things fall down.",
            evidence_refs=evidence,
        ),
        evidence_refs=evidence,
    )
    plan = plan_with(rule_update)
    assert apply_event_orders_to_plan(plan, {"e1": 0}) == plan


def test_is_a_no_op_without_orderable_anchors() -> None:
    plan = plan_with(state_update(state_id="state-a"))
    assert apply_event_orders_to_plan(plan, {"e1": 0}) == plan
    assert apply_event_orders_to_plan(plan, {}) == plan
