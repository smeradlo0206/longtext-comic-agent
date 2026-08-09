"""Validation and commit-boundary tests for StoryBible curation."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.database.models import (
    CandidateCommitPlanModel,
    StoryEntityProfileModel,
    StoryEntityStateModel,
    StoryRelationshipModel,
    WorldRuleModel,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
)
from comic_agent.services.commit_service import CommitService
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.storybible_validator import StoryBibleValidator


class ChunkLookup:
    """Small in-memory evidence boundary used with the real commit repository."""

    def __init__(self, *chunks: SourceChunkV1) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        return self._chunks.get(chunk_id)


@pytest.fixture()
def storybible_store(
    tmp_path: Path,
) -> Iterator[tuple[Session, StoryBibleRepository]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'commit.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    session: Session = session_factory()
    try:
        yield session, StoryBibleRepository(session)
    finally:
        session.close()
        engine.dispose()


def chunk(chunk_id: str = "chunk-a", project_id: str = "project-a") -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=chunk_id,
        document_id=f"document-{project_id}",
        chapter_id=f"chapter-{project_id}",
        project_id=project_id,
        order=0,
        text="Xia Ming waits at the market.",
        checksum=f"checksum-{chunk_id}",
    )


def profile_update(
    *,
    profile_id: str = "profile-1",
    project_id: str = "project-a",
    evidence_refs: list[EvidenceRefV1] | None = None,
) -> ProfileUpdateProposalV1:
    evidence = evidence_refs or [EvidenceRefV1(chunk_id="chunk-a")]
    profile = StoryEntityProfileV1(
        profile_id=profile_id,
        project_id=project_id,
        entity_kind="PERSON",
        canonical_name=f"Name {profile_id}",
        evidence_refs=evidence,
    )
    return ProfileUpdateProposalV1(
        update_id=f"update-{profile_id}",
        project_id=project_id,
        profile=profile,
        evidence_refs=evidence,
    )


def state_update(
    *,
    state_id: str = "state-1",
    project_id: str = "project-a",
    value: str = "market",
    valid_from_order: int | None = 2,
    valid_until_order: int | None = 4,
    valid_from_event_id: str | None = None,
    valid_until_event_id: str | None = None,
    evidence_refs: list[EvidenceRefV1] | None = None,
) -> StateUpdateProposalV1:
    evidence = evidence_refs or [EvidenceRefV1(chunk_id="chunk-a")]
    state = StoryEntityStateV1(
        state_id=state_id,
        project_id=project_id,
        profile_id="profile-1",
        state={"location": value},
        valid_from_event_id=valid_from_event_id,
        valid_until_event_id=valid_until_event_id,
        valid_from_order=valid_from_order,
        valid_until_order=valid_until_order,
        evidence_refs=evidence,
    )
    return StateUpdateProposalV1(
        update_id=f"update-{state_id}",
        project_id=project_id,
        state=state,
        evidence_refs=evidence,
    )


def plan(
    *updates: ProfileUpdateProposalV1 | StateUpdateProposalV1,
    evidence_refs: list[EvidenceRefV1] | None = None,
) -> CommitPlanV1:
    return CommitPlanV1(
        commit_plan_id="plan-1",
        project_id="project-a",
        source_proposal_id="proposal-1",
        content_hash="hash-1",
        updates=list(updates) or [profile_update()],
        evidence_refs=evidence_refs or [EvidenceRefV1(chunk_id="chunk-a")],
    )


def table_counts(session: Session) -> tuple[int, int, int, int, int]:
    models = (
        StoryEntityProfileModel,
        StoryEntityStateModel,
        StoryRelationshipModel,
        WorldRuleModel,
        CandidateCommitPlanModel,
    )
    return tuple(session.scalar(select(func.count()).select_from(model)) or 0 for model in models)


def test_commit_rejects_state_with_evidence_from_another_project(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    other_evidence = [EvidenceRefV1(chunk_id="chunk-b")]
    invalid_plan = plan(state_update(evidence_refs=other_evidence))
    service = CommitService(ChunkLookup(chunk(), chunk("chunk-b", "project-b")))

    with pytest.raises(ValueError, match="project"):
        service.commit_storybible_plan(invalid_plan, repository)

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_commit_validates_every_update_before_writing_any_canonical_row(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    invalid_plan = plan(
        profile_update(),
        state_update(evidence_refs=[EvidenceRefV1(chunk_id="missing")]),
    )

    with pytest.raises(ValueError, match="not found"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(invalid_plan, repository)

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_commit_rejects_cross_project_update_before_any_write(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    other_project_update = profile_update(profile_id="profile-b", project_id="project-b")
    invalid_plan = plan(profile_update(), other_project_update)

    with pytest.raises(ValueError, match="project"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(invalid_plan, repository)

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_commit_rejects_incompatible_state_values_at_the_same_anchor(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    invalid_plan = plan(
        state_update(state_id="state-1", value="market"),
        state_update(state_id="state-2", value="station"),
    )

    with pytest.raises(ValueError, match="incompatible"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(invalid_plan, repository)

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_commit_rejects_incompatible_state_values_in_overlapping_intervals(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    invalid_plan = plan(
        state_update(
            state_id="state-1",
            value="market",
            valid_from_order=1,
            valid_until_order=5,
        ),
        state_update(
            state_id="state-2",
            value="station",
            valid_from_order=3,
            valid_until_order=7,
        ),
    )

    with pytest.raises(ValueError, match="incompatible"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(invalid_plan, repository)

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_commit_allows_incompatible_state_values_at_distinct_event_only_anchors(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    event_anchored_plan = plan(
        state_update(
            state_id="state-1",
            value="market",
            valid_from_order=None,
            valid_until_order=None,
            valid_from_event_id="event-1",
        ),
        state_update(
            state_id="state-2",
            value="station",
            valid_from_order=None,
            valid_until_order=None,
            valid_from_event_id="event-2",
        ),
    )

    CommitService(ChunkLookup(chunk())).commit_storybible_plan(
        event_anchored_plan, repository
    )

    assert table_counts(session) == (0, 2, 0, 0, 1)


def test_commit_rejects_incompatible_state_values_at_identical_event_only_anchor(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    invalid_plan = plan(
        state_update(
            state_id="state-1",
            value="market",
            valid_from_order=None,
            valid_until_order=None,
            valid_from_event_id="event-1",
        ),
        state_update(
            state_id="state-2",
            value="station",
            valid_from_order=None,
            valid_until_order=None,
            valid_from_event_id="event-1",
        ),
    )

    with pytest.raises(ValueError, match="incompatible"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(
            invalid_plan, repository
        )

    assert table_counts(session) == (0, 0, 0, 0, 0)


def test_validator_defends_against_a_constructed_reversed_state_interval() -> None:
    evidence = [EvidenceRefV1(chunk_id="chunk-a")]
    malformed_state = StoryEntityStateV1.model_construct(
        state_id="state-1",
        project_id="project-a",
        profile_id="profile-1",
        state={"location": "market"},
        valid_from_order=5,
        valid_until_order=2,
        revision=1,
        status="CANONICAL",
        evidence_refs=evidence,
    )
    malformed_update = StateUpdateProposalV1.model_construct(
        update_id="update-state-1",
        project_id="project-a",
        state=malformed_state,
        evidence_refs=evidence,
    )
    malformed_plan = CommitPlanV1.model_construct(
        commit_plan_id="plan-1",
        project_id="project-a",
        source_proposal_id="proposal-1",
        content_hash="hash-1",
        updates=[malformed_update],
        evidence_refs=evidence,
    )

    with pytest.raises(ValueError, match="precede"):
        StoryBibleValidator(ChunkLookup(chunk())).validate_commit_plan(malformed_plan)


def test_repeated_approved_plan_is_idempotent(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    approved_plan = plan(profile_update())
    service = CommitService(ChunkLookup(chunk()))

    first = service.commit_storybible_plan(approved_plan, repository)
    counts_after_first = table_counts(session)
    second = service.commit_storybible_plan(approved_plan, repository)

    assert second == first
    assert table_counts(session) == counts_after_first == (1, 0, 0, 0, 1)


def test_commit_rejects_reused_plan_id_before_canonical_writes(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    stored = plan(profile_update(profile_id="stored-profile"))
    repository.save_candidate_plan(stored)
    counts_before = table_counts(session)
    conflicting = plan(profile_update(profile_id="new-profile")).model_copy(
        update={"content_hash": "different-hash"}
    )

    with pytest.raises(ValueError, match="commit_plan_id"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(conflicting, repository)

    assert table_counts(session) == counts_before == (0, 0, 0, 0, 1)


def test_commit_rejects_globally_reused_plan_id_before_canonical_writes(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    other_project_plan = CommitPlanV1(
        commit_plan_id="plan-1",
        project_id="project-b",
        source_proposal_id="proposal-b",
        content_hash="hash-b",
        updates=[profile_update(profile_id="profile-b", project_id="project-b")],
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-b")],
    )
    repository.save_candidate_plan(other_project_plan)
    counts_before = table_counts(session)

    with pytest.raises(ValueError, match="commit_plan_id"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(
            plan(profile_update(profile_id="new-profile")), repository
        )

    assert table_counts(session) == counts_before == (0, 0, 0, 0, 1)


def test_commit_rejects_later_cross_project_resource_id_before_any_write(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    session, repository = storybible_store
    repository.apply_canonical_update(
        state_update(state_id="shared-state", project_id="project-b").state,
        "seed-plan",
    )
    counts_before = table_counts(session)
    conflicting = plan(
        profile_update(profile_id="new-profile"),
        state_update(state_id="shared-state"),
    )

    with pytest.raises(ValueError, match="another project"):
        CommitService(ChunkLookup(chunk())).commit_storybible_plan(conflicting, repository)

    assert table_counts(session) == counts_before == (0, 1, 0, 0, 0)


def test_validate_proposal_enforces_proposal_plan_identity() -> None:
    proposal = StoryBibleCuratorProposalV1(
        proposal_id="proposal-1",
        project_id="project-a",
        commit_plan=plan(profile_update()).model_copy(
            update={"source_proposal_id": "different-proposal"}
        ),
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-a")],
        confidence=0.9,
    )

    with pytest.raises(ValueError, match="source_proposal_id"):
        StoryBibleValidator(ChunkLookup(chunk())).validate_proposal(proposal)


def test_storybible_context_is_selected_project_scoped_and_bounded(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    _, repository = storybible_store
    evidence = [EvidenceRefV1(chunk_id="chunk-a")]
    for update in (profile_update(profile_id="profile-1"), profile_update(profile_id="profile-2")):
        repository.apply_canonical_update(update, "seed-plan")
    repository.apply_canonical_update(
        profile_update(profile_id="other-profile", project_id="project-b"), "other-plan"
    )
    for index in range(5):
        repository.apply_canonical_update(
            StoryEntityStateV1(
                state_id=f"state-{index}",
                project_id="project-a",
                profile_id="profile-1",
                state={"sequence": index},
                evidence_refs=evidence,
            ),
            "seed-plan",
        )

    context = ContextBuilder().storybible_context(
        project_id="project-a",
        profile_ids=["profile-1"],
        source_chunks=[chunk(f"chunk-{index}") for index in range(5)],
        repository=repository,
    )

    assert [profile.profile_id for profile in context.profiles] == ["profile-1"]
    assert [state.state_id for state in context.states] == ["state-0", "state-1", "state-2"]
    assert context.relationships == []
    assert context.source_chunk_ids == ["chunk-0", "chunk-1", "chunk-2"]


def test_storybible_context_caps_profiles_after_loading_their_related_resources(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    """The last selected profile must retain its repository-loaded related state."""

    _, repository = storybible_store
    for index in range(4):
        repository.apply_canonical_update(
            profile_update(profile_id=f"profile-{index}"), "seed-plan"
        )
    repository.apply_canonical_update(
        StoryEntityStateV1(
            state_id="state-profile-2",
            project_id="project-a",
            profile_id="profile-2",
            state={"location": "market"},
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-a")],
        ),
        "seed-plan",
    )

    context = ContextBuilder().storybible_context(
        project_id="project-a",
        profile_ids=[f"profile-{index}" for index in range(4)],
        source_chunks=[],
        repository=repository,
    )

    assert [profile.profile_id for profile in context.profiles] == [
        "profile-0",
        "profile-1",
        "profile-2",
    ]
    assert [state.state_id for state in context.states] == ["state-profile-2"]


def test_storybible_context_caps_related_resources_across_selected_profiles(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    """Multiple selected profiles must not expand the bounded agent context."""

    _, repository = storybible_store
    for profile_id in ("profile-1", "profile-2"):
        repository.apply_canonical_update(profile_update(profile_id=profile_id), "seed-plan")
        for index in range(3):
            repository.apply_canonical_update(
                StoryEntityStateV1(
                    state_id=f"state-{profile_id}-{index}",
                    project_id="project-a",
                    profile_id=profile_id,
                    state={"location": f"place-{index}"},
                    evidence_refs=[EvidenceRefV1(chunk_id="chunk-a")],
                ),
                "seed-plan",
            )

    context = ContextBuilder().storybible_context(
        project_id="project-a",
        profile_ids=["profile-1", "profile-2"],
        source_chunks=[],
        repository=repository,
    )

    assert [state.state_id for state in context.states] == [
        "state-profile-1-0",
        "state-profile-1-1",
        "state-profile-1-2",
    ]


def test_storybible_context_rejects_cross_project_source_chunks(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    _, repository = storybible_store

    with pytest.raises(ValueError, match="project"):
        ContextBuilder().storybible_context(
            project_id="project-a",
            profile_ids=[],
            source_chunks=[chunk("chunk-b", "project-b")],
            repository=repository,
        )


def test_storybible_context_checks_project_scope_before_truncating_chunks(
    storybible_store: tuple[Session, StoryBibleRepository],
) -> None:
    _, repository = storybible_store
    chunks = [chunk(f"chunk-{index}") for index in range(3)]
    chunks.append(chunk("chunk-b", "project-b"))

    with pytest.raises(ValueError, match="project"):
        ContextBuilder().storybible_context(
            project_id="project-a",
            profile_ids=[],
            source_chunks=chunks,
            repository=repository,
        )
