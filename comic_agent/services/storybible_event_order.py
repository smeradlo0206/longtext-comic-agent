"""Apply timeline-provided event orders to StoryBible state intervals.

The parallel timeline agent owns event ordering. This module only CONSUMES the orders
it produced: it stamps state and relationship intervals with ``valid_from_order`` /
``valid_until_order`` so the state library can answer "what is the world like at this
moment". It never derives event order from temporal relations.
"""

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
