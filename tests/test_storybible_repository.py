"""Persistence tests for project-scoped StoryBible resources."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas import EvidenceRefV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)

EVIDENCE = [EvidenceRefV1(chunk_id="chunk-1")]


@pytest.fixture()
def storybible_repository(tmp_path: Path) -> Iterator[StoryBibleRepository]:
    """Provide a repository backed by an isolated real SQLite database."""

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storybible.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        yield StoryBibleRepository(session)
    finally:
        session.close()
        engine.dispose()


def profile(
    *,
    profile_id: str = "p-1",
    project_id: str = "project-a",
    aliases: list[str] | None = None,
    revision: int = 1,
    canonical_name: str = "Xia Ming",
) -> StoryEntityProfileV1:
    return StoryEntityProfileV1(
        profile_id=profile_id,
        project_id=project_id,
        entity_kind="PERSON",
        canonical_name=canonical_name,
        aliases=aliases or [],
        revision=revision,
        evidence_refs=EVIDENCE,
    )


def candidate_plan(
    *,
    plan_id: str = "plan-1",
    project_id: str = "project-a",
    content_hash: str = "hash-1",
    canonical_name: str = "Xia Ming",
) -> CommitPlanV1:
    stored_profile = profile(project_id=project_id, canonical_name=canonical_name)
    update = ProfileUpdateProposalV1(
        update_id=f"update-{plan_id}",
        project_id=project_id,
        profile=stored_profile,
        evidence_refs=EVIDENCE,
    )
    return CommitPlanV1(
        commit_plan_id=plan_id,
        project_id=project_id,
        source_proposal_id=f"proposal-{plan_id}",
        content_hash=content_hash,
        updates=[update],
        evidence_refs=EVIDENCE,
    )


def test_find_profiles_scopes_alias_search_to_one_project(
    storybible_repository: StoryBibleRepository,
) -> None:
    """An alias collision in another project must not leak into search results."""

    storybible_repository.apply_canonical_update(
        profile(project_id="project-a", aliases=["Xia"]), plan_id="plan-a"
    )
    storybible_repository.apply_canonical_update(
        profile(profile_id="p-2", project_id="project-b", aliases=["Xia"]),
        plan_id="plan-b",
    )

    assert [
        item.profile_id for item in storybible_repository.find_profiles("project-a", "xia")
    ] == ["p-1"]


def test_get_profile_requires_matching_project(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Knowing an id must not expose a profile owned by another project."""

    storybible_repository.apply_canonical_update(profile(), plan_id="plan-a")

    assert storybible_repository.get_profile("project-b", "p-1") is None


def test_save_candidate_plan_is_idempotent_by_project_and_content_hash(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Equivalent plans in one project must reuse the first persisted candidate."""

    first = storybible_repository.save_candidate_plan(candidate_plan())
    second = storybible_repository.save_candidate_plan(
        candidate_plan(plan_id="plan-2", canonical_name="A different serialization")
    )

    assert second == first
    assert second.commit_plan_id == "plan-1"
    assert storybible_repository.get_plan_by_content_hash("project-a", "hash-1") == first


def test_candidate_plan_hash_is_scoped_to_project(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Two projects may independently persist the same deterministic content hash."""

    project_a = storybible_repository.save_candidate_plan(candidate_plan())
    project_b = storybible_repository.save_candidate_plan(
        candidate_plan(plan_id="plan-2", project_id="project-b")
    )

    assert project_a.commit_plan_id == "plan-1"
    assert project_b.commit_plan_id == "plan-2"


def test_get_plan_requires_matching_project(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Knowing a plan id must not expose another project's candidate."""

    plan = storybible_repository.save_candidate_plan(candidate_plan())

    assert storybible_repository.get_plan("project-a", "plan-1") == plan
    assert storybible_repository.get_plan("project-b", "plan-1") is None


def test_save_committed_plan_is_idempotent(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Repeated completion of the same persisted plan returns the canonical plan."""

    plan = candidate_plan()

    first = storybible_repository.save_committed_plan(plan)
    second = storybible_repository.save_committed_plan(plan)

    assert first == plan
    assert second == first


def test_canonical_update_only_accepts_a_higher_revision(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Retries and stale plans must not replace a newer canonical resource."""

    first = storybible_repository.apply_canonical_update(profile(), plan_id="plan-1")
    equal = storybible_repository.apply_canonical_update(
        profile(canonical_name="Equal revision"), plan_id="plan-2"
    )
    newer = storybible_repository.apply_canonical_update(
        profile(canonical_name="New name", revision=2), plan_id="plan-3"
    )
    stale = storybible_repository.apply_canonical_update(
        profile(canonical_name="Stale name", revision=1), plan_id="plan-4"
    )

    assert equal == first
    assert newer.canonical_name == "New name"
    assert stale == newer
    assert storybible_repository.get_profile("project-a", "p-1") == newer


def test_list_states_at_event_returns_only_active_project_states(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Temporal lookup must honor inclusive boundaries and project ownership."""

    active = StoryEntityStateV1(
        state_id="state-active",
        project_id="project-a",
        profile_id="p-1",
        state={"location": "market"},
        valid_from_order=2,
        valid_until_order=4,
        evidence_refs=EVIDENCE,
    )
    expired = active.model_copy(
        update={"state_id": "state-expired", "valid_from_order": 0, "valid_until_order": 1}
    )
    other_project = active.model_copy(
        update={"state_id": "state-other", "project_id": "project-b"}
    )
    for resource in (active, expired, other_project):
        storybible_repository.apply_canonical_update(resource, plan_id="plan-1")

    assert storybible_repository.list_states_at_event("project-a", 4) == [active]


def test_list_related_resources_is_project_scoped(
    storybible_repository: StoryBibleRepository,
) -> None:
    """Related states and relationships must not include another project's records."""

    state = StoryEntityStateV1(
        state_id="state-1",
        project_id="project-a",
        profile_id="p-1",
        state={"mood": "calm"},
        evidence_refs=EVIDENCE,
    )
    relationship = StoryRelationshipV1(
        relationship_id="relationship-1",
        project_id="project-a",
        source_profile_id="p-2",
        target_profile_id="p-1",
        relationship_type="ALLY",
        evidence_refs=EVIDENCE,
    )
    unrelated = relationship.model_copy(
        update={
            "relationship_id": "relationship-2",
            "source_profile_id": "p-3",
            "target_profile_id": "p-4",
        }
    )
    other_project = state.model_copy(update={"state_id": "state-2", "project_id": "project-b"})
    for resource in (state, relationship, unrelated, other_project):
        storybible_repository.apply_canonical_update(resource, plan_id="plan-1")

    assert storybible_repository.list_related_resources("project-a", "p-1") == [
        state,
        relationship,
    ]


def test_apply_canonical_update_accepts_a_proposal_wrapper(
    storybible_repository: StoryBibleRepository,
) -> None:
    """CommitService may pass a reviewed update wrapper without unwrapping it."""

    canonical_profile = profile()
    update = ProfileUpdateProposalV1(
        update_id="update-1",
        project_id="project-a",
        profile=canonical_profile,
        evidence_refs=EVIDENCE,
    )

    assert storybible_repository.apply_canonical_update(update, "plan-1") == canonical_profile


def test_apply_canonical_update_rejects_cross_project_wrapper(
    storybible_repository: StoryBibleRepository,
) -> None:
    """A malformed wrapper must not smuggle another project's canonical resource."""

    update = ProfileUpdateProposalV1(
        update_id="update-1",
        project_id="project-b",
        profile=profile(project_id="project-a"),
        evidence_refs=EVIDENCE,
    )

    with pytest.raises(ValueError, match="same project"):
        storybible_repository.apply_canonical_update(update, "plan-1")


def test_world_rules_are_persisted_and_listed_by_project(
    storybible_repository: StoryBibleRepository,
) -> None:
    """A project's world rules must persist without leaking another project's rules."""

    project_rule = WorldRuleV1(
        rule_id="rule-1",
        project_id="project-a",
        name="Names bind magic",
        statement="A spoken true name binds a spell.",
        evidence_refs=EVIDENCE,
    )
    other_rule = project_rule.model_copy(
        update={"rule_id": "rule-2", "project_id": "project-b"}
    )
    storybible_repository.apply_canonical_update(project_rule, "plan-1")
    storybible_repository.apply_canonical_update(other_rule, "plan-2")

    assert storybible_repository.list_world_rules("project-a") == [project_rule]
