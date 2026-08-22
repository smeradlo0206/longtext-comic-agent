"""Idempotency and immutability tests for StoryBible review persistence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.database.models import (
    StoryBibleProductionRunModel,
    StoryBibleReviewRunModel,
)
from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.repositories.storybible_review_repository import (
    StoryBibleReviewRepository,
)
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionRunV1,
    StoryBibleReviewContextV1,
    StoryBibleReviewIssueV1,
    StoryBibleReviewMetadataV1,
    StoryBibleReviewResultV1,
    StoryEntityProfileV1,
)
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)

EVIDENCE = EvidenceRefV1(chunk_id="chunk-1", quote_text="Xia Ming arrived.")
REVIEWED_AT = datetime(2026, 8, 23, tzinfo=UTC)
FROZEN_AT = datetime(2026, 8, 23, 1, tzinfo=UTC)


def _profile(name: str = "Xia Ming") -> StoryEntityProfileV1:
    return StoryEntityProfileV1(
        profile_id="profile-1",
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name=name,
        evidence_refs=[EVIDENCE],
    )


def _proposal() -> StoryBibleCuratorProposalV1:
    profile = _profile()
    return StoryBibleCuratorProposalV1(
        proposal_id="proposal-1",
        project_id="project-1",
        commit_plan=CommitPlanV1(
            commit_plan_id="plan-1",
            project_id="project-1",
            source_proposal_id="proposal-1",
            content_hash="content-hash-1",
            updates=[
                ProfileUpdateProposalV1(
                    update_id="update-1",
                    project_id="project-1",
                    profile=profile,
                    evidence_refs=[EVIDENCE],
                )
            ],
            evidence_refs=[EVIDENCE],
        ),
        evidence_refs=[EVIDENCE],
        confidence=1,
    )


def _seed_succeeded_run(session: Session) -> None:
    proposal = _proposal()
    snapshot = StoryBibleCanonicalSnapshotV1(project_id="project-1")
    run = StoryBibleProductionRunV1(
        run_id="run-1",
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=canonical_storybible_snapshot_hash(snapshot),
        input_hash="input-hash-1",
        model_identity="mock-model",
        status="SUCCEEDED",
        curator_proposal=proposal,
        agent_run_id="agent-run-1",
        provider_request_count=1,
        created_at=REVIEWED_AT,
        updated_at=REVIEWED_AT,
    )
    session.add(
        StoryBibleProductionRunModel(
            run_id=run.run_id,
            project_id=run.project_id,
            gate2_approved_bundle_id=run.gate2_approved_bundle_id,
            approved_timeline_bundle_id=run.approved_timeline_bundle_id,
            input_hash=run.input_hash,
            status=str(run.status),
            payload=run.model_dump(mode="json"),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
    )
    session.commit()


@pytest.fixture()
def repository(tmp_path: Path) -> tuple[StoryBibleReviewRepository, Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storybible-review.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    _seed_succeeded_run(session)
    return StoryBibleReviewRepository(session), session


def _review(*, decision: str = "APPROVE") -> StoryBibleReviewResultV1:
    issues = []
    if decision == "REJECT":
        issues = [
            StoryBibleReviewIssueV1(
                issue_id="issue-1",
                category="EVIDENCE_INVALID",
                severity="BLOCKING",
                message="Evidence does not resolve.",
                affected_ids=["profile-1"],
            )
        ]
    return StoryBibleReviewResultV1(
        review_id="review-1",
        project_id="project-1",
        storybible_run_id="run-1",
        proposal_hash=storybible_proposal_hash(_proposal()),
        decision=decision,
        issues=issues,
        validated_entities=[] if issues else ["profile-1"],
        reviewed_at=REVIEWED_AT,
    )


def _context(result: StoryBibleReviewResultV1 | None = None) -> StoryBibleReviewContextV1:
    result = result or _review()
    snapshot = StoryBibleCanonicalSnapshotV1(project_id=result.project_id)
    return StoryBibleReviewContextV1(
        review_id=result.review_id,
        project_id=result.project_id,
        source_storybible_run_id=result.storybible_run_id,
        source_approved_timeline_bundle_id="timeline-1",
        canonical_snapshot=snapshot,
        canonical_snapshot_hash=canonical_storybible_snapshot_hash(snapshot),
        proposal_hash=result.proposal_hash,
        reviewed_at=result.reviewed_at,
    )


def _bundle(*, snapshot_hash: str = "snapshot-hash-1") -> ApprovedStoryBibleBundleV1:
    return ApprovedStoryBibleBundleV1(
        bundle_id="bundle-1",
        project_id="project-1",
        source_storybible_run_id="run-1",
        snapshot_hash=snapshot_hash,
        entities=[_profile()],
        evidence_refs=[EVIDENCE],
        review_metadata=StoryBibleReviewMetadataV1(
            review_id="review-1",
            decision="APPROVE",
            proposal_hash=storybible_proposal_hash(_proposal()),
            source_approved_timeline_bundle_id="timeline-1",
            reviewed_at=REVIEWED_AT,
            frozen_at=FROZEN_AT,
        ),
    )


def test_save_review_is_idempotent_per_production_run(
    repository: tuple[StoryBibleReviewRepository, Session],
) -> None:
    store, session = repository
    result = _review()
    first = store.save_review(_context(result), result)
    replay_result = _review().model_copy(
        update={"reviewed_at": datetime(2026, 8, 23, 2, tzinfo=UTC)}
    )
    replay = store.save_review(
        _context(replay_result), replay_result
    )

    assert replay == first
    assert session.scalar(select(func.count()).select_from(StoryBibleReviewRunModel)) == 1
    with pytest.raises(ValueError, match="different review"):
        rejected = _review(decision="REJECT")
        store.save_review(_context(rejected), rejected)


def test_review_requires_succeeded_matching_production_run(
    repository: tuple[StoryBibleReviewRepository, Session],
) -> None:
    store, _ = repository
    with pytest.raises(ValueError, match="another project"):
        result = _review().model_copy(update={"project_id": "project-2"})
        store.save_review(_context(result), result)
    with pytest.raises(ValueError, match="not found"):
        result = _review().model_copy(update={"storybible_run_id": "missing"})
        store.save_review(_context(result), result)


def test_freeze_is_atomic_idempotent_and_immutable(
    repository: tuple[StoryBibleReviewRepository, Session],
) -> None:
    store, _ = repository
    result = _review()
    store.save_review(_context(result), result)

    first = store.freeze("review-1", _bundle())
    replay = store.freeze("review-1", _bundle())

    assert first == replay
    assert first.status == "FROZEN"
    assert first.approved_bundle == _bundle()
    with pytest.raises(ValueError, match="immutable"):
        store.freeze("review-1", _bundle(snapshot_hash="changed-hash"))


def test_non_approved_review_cannot_freeze(
    repository: tuple[StoryBibleReviewRepository, Session],
) -> None:
    store, _ = repository
    result = _review(decision="REJECT")
    store.save_review(_context(result), result)

    with pytest.raises(ValueError, match="only an APPROVE"):
        store.freeze("review-1", _bundle())
