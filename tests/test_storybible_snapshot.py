"""Deterministic world-state snapshots with cross-chapter inheritance."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)
from comic_agent.services.storybible_snapshot import build_state_snapshot

EVIDENCE = [EvidenceRefV1(chunk_id="chunk-a")]


@pytest.fixture()
def storybible_repository(tmp_path: Path) -> Iterator[StoryBibleRepository]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        yield StoryBibleRepository(session)
    finally:
        session.close()
        engine.dispose()


def profile(
    repository: StoryBibleRepository,
    *,
    profile_id: str,
    name: str,
    entity_kind: str = "PERSON",
    project_id: str = "project-a",
) -> None:
    repository.apply_canonical_update(
        StoryEntityProfileV1(
            profile_id=profile_id,
            project_id=project_id,
            entity_kind=entity_kind,
            canonical_name=name,
            evidence_refs=EVIDENCE,
        ),
        plan_id="plan-profile",
    )


def state(
    repository: StoryBibleRepository,
    *,
    state_id: str,
    profile_id: str,
    attributes: dict,
    valid_from_order: int | None = 0,
    valid_until_order: int | None = None,
    from_event_id: str | None = None,
) -> None:
    repository.apply_canonical_update(
        StoryEntityStateV1(
            state_id=state_id,
            project_id="project-a",
            profile_id=profile_id,
            state=attributes,
            valid_from_order=valid_from_order,
            valid_until_order=valid_until_order,
            valid_from_event_id=from_event_id,
            evidence_refs=EVIDENCE,
        ),
        plan_id=f"plan-{state_id}",
    )


def test_earlier_chapter_state_survives_later_chapters(
    storybible_repository: StoryBibleRepository,
) -> None:
    """A fact established in chapter one stays visible at a chapter-five moment."""

    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    state(
        storybible_repository,
        state_id="s1",
        profile_id="p1",
        attributes={"appearance": {"clothing": "黑金外套"}},
        valid_from_order=0,
    )

    snapshot = build_state_snapshot(storybible_repository, "project-a", event_order=40)

    assert [character.profile_id for character in snapshot.characters] == ["p1"]
    assert snapshot.characters[0].state["appearance.clothing"] == "黑金外套"
    assert snapshot.characters[0].state_ids == ["s1"]
    assert snapshot.unresolved_state_ids == []


def test_later_change_overrides_an_inherited_value(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    state(
        storybible_repository,
        state_id="s1",
        profile_id="p1",
        attributes={"appearance": {"clothing": "黑金外套"}},
        valid_from_order=0,
    )
    state(
        storybible_repository,
        state_id="s2",
        profile_id="p1",
        attributes={"appearance": {"clothing": "素白长裙"}},
        valid_from_order=5,
    )

    before = build_state_snapshot(storybible_repository, "project-a", event_order=3)
    after = build_state_snapshot(storybible_repository, "project-a", event_order=6)

    assert before.characters[0].state["appearance.clothing"] == "黑金外套"
    assert after.characters[0].state["appearance.clothing"] == "素白长裙"


def test_temporary_state_expires_after_its_until_order(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    state(
        storybible_repository,
        state_id="s1",
        profile_id="p1",
        attributes={"appearance": {"clothing": "常服"}},
        valid_from_order=0,
    )
    state(
        storybible_repository,
        state_id="s2",
        profile_id="p1",
        attributes={"appearance": {"clothing": "夜行衣"}},
        valid_from_order=4,
        valid_until_order=6,
    )

    during = build_state_snapshot(storybible_repository, "project-a", event_order=5)
    after = build_state_snapshot(storybible_repository, "project-a", event_order=7)

    assert during.characters[0].state["appearance.clothing"] == "夜行衣"
    assert after.characters[0].state["appearance.clothing"] == "常服"


def test_unordered_state_is_treated_as_timeless_and_flagged(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    state(
        storybible_repository,
        state_id="s1",
        profile_id="p1",
        attributes={"appearance": {"hair": "银白"}},
        valid_from_order=None,
    )
    state(
        storybible_repository,
        state_id="s2",
        profile_id="p1",
        attributes={"appearance": {"hair": "黑色"}},
        valid_from_order=2,
    )

    before_change = build_state_snapshot(storybible_repository, "project-a", event_order=1)
    after_change = build_state_snapshot(storybible_repository, "project-a", event_order=2)

    assert before_change.characters[0].state["appearance.hair"] == "银白"
    assert after_change.characters[0].state["appearance.hair"] == "黑色"
    assert after_change.characters[0].unresolved_state_ids == ["s1"]
    assert after_change.unresolved_state_ids == ["s1"]


def test_snapshot_groups_profiles_by_entity_kind(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia", entity_kind="PERSON")
    profile(
        storybible_repository,
        profile_id="l1",
        name="北境城",
        entity_kind="LOCATION",
    )
    profile(
        storybible_repository,
        profile_id="o1",
        name="青云宗",
        entity_kind="ORGANIZATION",
    )

    snapshot = build_state_snapshot(storybible_repository, "project-a", event_order=0)

    assert [item.profile_id for item in snapshot.characters] == ["p1"]
    assert [item.profile_id for item in snapshot.locations] == ["l1"]
    assert [item.profile_id for item in snapshot.organizations] == ["o1"]


def test_snapshot_includes_active_relationships_and_world_rules(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    profile(storybible_repository, profile_id="p2", name="Su Yan")
    storybible_repository.apply_canonical_update(
        StoryRelationshipV1(
            relationship_id="r1",
            project_id="project-a",
            source_profile_id="p1",
            target_profile_id="p2",
            relationship_type="ALLY",
            valid_from_order=1,
            valid_until_order=10,
            evidence_refs=EVIDENCE,
        ),
        plan_id="plan-r1",
    )
    storybible_repository.apply_canonical_update(
        StoryRelationshipV1(
            relationship_id="r2",
            project_id="project-a",
            source_profile_id="p1",
            target_profile_id="p2",
            relationship_type="RIVAL",
            valid_from_order=20,
            evidence_refs=EVIDENCE,
        ),
        plan_id="plan-r2",
    )
    storybible_repository.apply_canonical_update(
        WorldRuleV1(
            rule_id="w1",
            project_id="project-a",
            name="灵气",
            statement="灵气充盈之地可施展法术。",
            evidence_refs=EVIDENCE,
        ),
        plan_id="plan-w1",
    )

    early = build_state_snapshot(storybible_repository, "project-a", event_order=3)
    later = build_state_snapshot(storybible_repository, "project-a", event_order=25)

    assert [item.relationship_type for item in early.relationships] == ["ALLY"]
    assert [item.relationship_type for item in later.relationships] == ["RIVAL"]
    assert [rule.name for rule in early.world_rules] == ["灵气"]
    assert [rule.name for rule in later.world_rules] == ["灵气"]


def test_snapshot_is_deterministic_for_the_same_moment(
    storybible_repository: StoryBibleRepository,
) -> None:
    profile(storybible_repository, profile_id="p1", name="Lin Xia")
    state(
        storybible_repository,
        state_id="s1",
        profile_id="p1",
        attributes={"location": "market"},
        valid_from_order=0,
    )

    first = build_state_snapshot(storybible_repository, "project-a", event_order=2)
    second = build_state_snapshot(storybible_repository, "project-a", event_order=2)

    assert first == second


def test_snapshot_is_project_scoped(storybible_repository: StoryBibleRepository) -> None:
    profile(
        storybible_repository,
        profile_id="p1",
        name="Lin Xia",
        project_id="project-b",
    )

    snapshot = build_state_snapshot(storybible_repository, "project-a", event_order=0)

    assert snapshot.characters == []
    assert snapshot.locations == []
    assert snapshot.relationships == []
    assert snapshot.world_rules == []
