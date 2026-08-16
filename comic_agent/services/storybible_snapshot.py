"""Deterministic world-state snapshot at one story moment.

The state library persists across chapter imports. A state interval is effective from
its from-event onward until a later change (or its until-event), so a chapter that
never mentions an established fact still inherits it. This module folds the canonical
intervals that are in effect at a requested timeline event order into one resolved
view per profile — without any model call and without touching canonical storage.
"""

from collections.abc import Iterable
from typing import Any

from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.storybible import (
    ResolvedProfileStateV1,
    StoryBibleSnapshotV1,
    StoryEntityKind,
    StoryEntityProfileV1,
    StoryEntityStateV1,
)


def build_state_snapshot(
    repository: StoryBibleRepository,
    project_id: str,
    event_order: int,
) -> StoryBibleSnapshotV1:
    """Return the resolved world state at one timeline event order."""

    profiles = repository.list_profiles(project_id)
    active_states = repository.list_states_at_event(project_id, event_order)
    merged_by_profile = _merge_active_states(profiles, active_states)

    characters = [
        resolved for resolved in merged_by_profile.values()
        if resolved.entity_kind == StoryEntityKind.PERSON
    ]
    locations = [
        resolved for resolved in merged_by_profile.values()
        if resolved.entity_kind == StoryEntityKind.LOCATION
    ]
    organizations = [
        resolved for resolved in merged_by_profile.values()
        if resolved.entity_kind == StoryEntityKind.ORGANIZATION
    ]

    relationships = [
        relationship
        for relationship in repository.list_relationships(project_id)
        if _interval_active_at(
            relationship.valid_from_order,
            relationship.valid_until_order,
            event_order,
        )
    ]

    unresolved_state_ids = sorted(
        {
            state.state_id
            for state in active_states
            if state.valid_from_order is None
        }
    )

    return StoryBibleSnapshotV1(
        project_id=project_id,
        event_order=event_order,
        characters=characters,
        locations=locations,
        organizations=organizations,
        relationships=relationships,
        world_rules=repository.list_world_rules(project_id),
        unresolved_state_ids=unresolved_state_ids,
    )


def _merge_active_states(
    profiles: list[StoryEntityProfileV1],
    active_states: list[StoryEntityStateV1],
) -> dict[str, ResolvedProfileStateV1]:
    """Overlay every in-effect state of a profile in deterministic order.

    States with a known from-order are ordered by that order; states whose story
    order is unknown are treated as timeless and are applied first, then flagged as
    unresolved. Later overlays override earlier values on the same attribute path.
    """

    states_by_profile: dict[str, list[StoryEntityStateV1]] = {}
    for state in active_states:
        states_by_profile.setdefault(state.profile_id, []).append(state)

    resolved: dict[str, ResolvedProfileStateV1] = {}
    for profile in profiles:
        profile_states = sorted(
            states_by_profile.get(profile.profile_id, ()),
            key=lambda state: (
                state.valid_from_order is not None,
                state.valid_from_order if state.valid_from_order is not None else -1,
                state.state_id,
            ),
        )
        merged: dict[str, Any] = {}
        state_ids: list[str] = []
        unresolved_state_ids: list[str] = []
        for state in profile_states:
            for path, value in _flatten_state(state.state):
                merged[path] = value
            state_ids.append(state.state_id)
            if state.valid_from_order is None:
                unresolved_state_ids.append(state.state_id)
        resolved[profile.profile_id] = ResolvedProfileStateV1(
            profile_id=profile.profile_id,
            project_id=profile.project_id,
            canonical_name=profile.canonical_name,
            entity_kind=profile.entity_kind,
            state=merged,
            state_ids=state_ids,
            unresolved_state_ids=unresolved_state_ids,
        )
    return resolved


def _interval_active_at(
    valid_from_order: int | None,
    valid_until_order: int | None,
    event_order: int,
) -> bool:
    """Return whether an inclusive order interval covers the requested order."""

    if valid_from_order is not None and valid_from_order > event_order:
        return False
    if valid_until_order is not None and valid_until_order < event_order:
        return False
    return True


def _flatten_state(state: dict[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key in sorted(state):
        path = f"{prefix}.{key}" if prefix else key
        value = state[key]
        if isinstance(value, dict):
            yield from _flatten_state(value, path)
        else:
            yield path, value
