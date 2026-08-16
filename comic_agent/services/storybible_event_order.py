"""Deterministic story-event ordering derived from confirmed temporal relations."""

from collections.abc import Iterable

from comic_agent.schemas.narrative import TemporalRelation, TemporalRelationProposalV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    WorldRuleUpdateProposalV1,
)

type StoryBibleUpdate = (
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1
)


def assign_event_orders(
    temporal_relations: Iterable[TemporalRelationProposalV1],
    event_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Assign each event a deterministic story order from BEFORE/AFTER relations.

    Only strict BEFORE/AFTER edges constrain the order; DURING, CONTAINS, OVERLAPS,
    SIMULTANEOUS, and UNKNOWN relations impose no ordering. The order of an event is
    its longest-path depth in the directed graph, so chained relations produce
    monotonically increasing orders. Events inside a cycle and events unreachable
    from any root receive no order. Tie-breaking sorts candidate edges by event id,
    making the assignment deterministic for the same input.

    Returns a mapping of event id to non-negative order; unassigned events are absent.
    """

    graph: dict[str, set[str]] = {event_id: set() for event_id in event_ids}
    indegree: dict[str, int] = {event_id: 0 for event_id in graph}

    for relation in temporal_relations:
        if relation.relation == TemporalRelation.BEFORE:
            source, target = relation.source_event_id, relation.target_event_id
        elif relation.relation == TemporalRelation.AFTER:
            source, target = relation.target_event_id, relation.source_event_id
        else:
            continue
        for node in (source, target):
            if node not in graph:
                graph[node] = set()
                indegree[node] = 0
        if target not in graph[source]:
            graph[source].add(target)
            indegree[target] += 1

    orders: dict[str, int] = {event_id: 0 for event_id in graph if indegree[event_id] == 0}
    remaining = {event_id for event_id in indegree if indegree[event_id] > 0}
    frontier = sorted(orders)
    while frontier:
        next_frontier: list[str] = []
        for node in frontier:
            for successor in sorted(graph[node]):
                indegree[successor] -= 1
                orders[successor] = max(orders.get(successor, 0), orders[node] + 1)
                if indegree[successor] == 0:
                    remaining.discard(successor)
                    next_frontier.append(successor)
        frontier = sorted(next_frontier)

    for cyclic_or_unreached in remaining:
        orders.pop(cyclic_or_unreached, None)
    return orders


def apply_event_orders_to_plan(
    plan: CommitPlanV1,
    event_orders: dict[str, int],
) -> CommitPlanV1:
    """Fill missing state/relationship order fields from assigned event orders.

    ``valid_from_order`` takes the order of the from/triggering event. Because
    StoryBible intervals are inclusive on both ends, ``valid_until_order`` takes the
    until event's order minus one so a state ending at an event never overlaps the
    next state starting at that same event. Guards preserve existing model-provided
    values, keep orders non-negative, and never build an inverted interval.
    """

    updated_updates: list[StoryBibleUpdate] = []
    changed = False
    for update in plan.updates:
        if isinstance(update, StateUpdateProposalV1):
            state = update.state
            from_event_id = state.valid_from_event_id or state.triggering_event_id
            new_from = state.valid_from_order
            new_until = state.valid_until_order
            if new_from is None and from_event_id is not None:
                new_from = event_orders.get(from_event_id)
            if new_until is None and state.valid_until_event_id is not None:
                until_order = event_orders.get(state.valid_until_event_id)
                if until_order is not None and until_order >= 1:
                    candidate_until = until_order - 1
                    if new_from is None or candidate_until >= new_from:
                        new_until = candidate_until
            if new_from != state.valid_from_order or new_until != state.valid_until_order:
                update = update.model_copy(
                    update={
                        "state": state.model_copy(
                            update={"valid_from_order": new_from, "valid_until_order": new_until}
                        )
                    }
                )
                changed = True
        elif isinstance(update, RelationshipUpdateProposalV1):
            relationship = update.relationship
            new_from = relationship.valid_from_order
            new_until = relationship.valid_until_order
            if new_from is None and relationship.valid_from_event_id is not None:
                new_from = event_orders.get(relationship.valid_from_event_id)
            if new_until is None and relationship.valid_until_event_id is not None:
                until_order = event_orders.get(relationship.valid_until_event_id)
                if until_order is not None and until_order >= 1:
                    candidate_until = until_order - 1
                    if new_from is None or candidate_until >= new_from:
                        new_until = candidate_until
            if (
                new_from != relationship.valid_from_order
                or new_until != relationship.valid_until_order
            ):
                update = update.model_copy(
                    update={
                        "relationship": relationship.model_copy(
                            update={"valid_from_order": new_from, "valid_until_order": new_until}
                        )
                    }
                )
                changed = True
        updated_updates.append(update)

    if not changed:
        return plan
    return plan.model_copy(update={"updates": updated_updates})
