"""Join the timeline agent's relation output onto StoryBible state intervals.

The parallel timeline agent emits pairwise `TemporalRelationProposalV1` records
(BEFORE/AFTER/SIMULTANEOUS/OVERLAPS/DURING/CONTAINS/UNKNOWN). This module consumes
that output: it derives deterministic sequence stamps only for events constrained by
real BEFORE/AFTER edges, and applies them to missing `valid_from_order` /
`valid_until_order` fields. It never extracts ordering from raw text, and it stamps
nothing when the timeline provided no real ordering constraints.
"""

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
) -> dict[str, int]:
    """Assign deterministic sequence numbers from the timeline agent's relations.

    Only strict BEFORE/AFTER edges constrain the order; DURING, CONTAINS, OVERLAPS,
    SIMULTANEOUS, and UNKNOWN impose none. An event's order is its longest-path depth
    in the directed graph. Events not incident to any real edge, events inside a
    cycle, and events whose relations are all UNKNOWN receive no order, so a
    RULES_ONLY timeline analysis (which emits only UNKNOWN relations) stamps nothing
    and never fabricates false conflicts. Tie-breaking sorts by event id, making the
    assignment deterministic for the same input.
    """

    edges: set[tuple[str, str]] = set()
    for relation in temporal_relations:
        if relation.relation == TemporalRelation.BEFORE:
            edges.add((relation.source_event_id, relation.target_event_id))
        elif relation.relation == TemporalRelation.AFTER:
            edges.add((relation.target_event_id, relation.source_event_id))

    if not edges:
        return {}

    participants: set[str] = set()
    for source, target in edges:
        participants.add(source)
        participants.add(target)

    graph: dict[str, set[str]] = {node: set() for node in participants}
    indegree: dict[str, int] = {node: 0 for node in participants}
    for source, target in edges:
        if target not in graph[source]:
            graph[source].add(target)
            indegree[target] += 1

    orders: dict[str, int] = {node: 0 for node in participants if indegree[node] == 0}
    remaining = {node for node in participants if indegree[node] > 0}
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

    for cyclic_node in remaining:
        orders.pop(cyclic_node, None)

    return orders


def apply_event_orders_to_plan(
    plan: CommitPlanV1,
    event_orders: dict[str, int],
) -> CommitPlanV1:
    """Fill missing order fields from the timeline-provided event orders.

    ``valid_from_order`` takes the order of the from/triggering event. Because
    StoryBible intervals are inclusive on both ends, ``valid_until_order`` takes the
    until event's order minus one so a state ending at an event never overlaps the
    next state starting at that same event. Guards preserve existing values, keep
    orders non-negative, and never build an inverted interval.
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
