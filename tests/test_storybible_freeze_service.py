"""Canonical StoryBible freeze uses CommitService and produces immutable output."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.database.models import StoryBibleProductionRunModel
from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.repositories.storybible_review_repository import (
    StoryBibleReviewRepository,
)
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionRunV1,
    StoryBibleReviewContextV1,
    StoryBibleReviewRunV1,
    StoryEntityProfileV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.storybible_freeze_service import StoryBibleFreezeService
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)
from comic_agent.services.storybible_review_service import StoryBibleReviewService

NOW = datetime(2026, 8, 23, tzinfo=UTC)
FROZEN_AT = datetime(2026, 8, 23, 1, tzinfo=UTC)
TEXT = "Xia Ming arrived."
EVIDENCE = EvidenceRefV1(chunk_id="chunk-1", quote_start=0, quote_end=8, quote_text="Xia Ming")


class ChunkLookup:
    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        if chunk_id != "chunk-1":
            return None
        return SourceChunkV1(
            chunk_id="chunk-1",
            project_id="project-1",
            document_id="document-1",
            chapter_id="chapter-1",
            order=0,
            text=TEXT,
            checksum="checksum-1",
        )


class RecordingCommitService(CommitService):
    def __init__(self) -> None:
        super().__init__(ChunkLookup())
        self.calls = 0

    def commit_storybible_plan(
        self, plan: CommitPlanV1, repository: StoryBibleRepository
    ) -> CommitPlanV1:
        self.calls += 1
        return super().commit_storybible_plan(plan, repository)


def _proposal() -> StoryBibleCuratorProposalV1:
    profile = StoryEntityProfileV1(
        profile_id="profile-1",
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name="Xia Ming",
        evidence_refs=[EVIDENCE],
    )
    plan = CommitPlanV1(
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
    )
    return StoryBibleCuratorProposalV1(
        proposal_id="proposal-1",
        project_id="project-1",
        commit_plan=plan,
        evidence_refs=[EVIDENCE],
        confidence=1,
    )


def _timeline() -> ApprovedTimelineBundleV1:
    return ApprovedTimelineBundleV1(
        bundle_id="timeline-1",
        project_id="project-1",
        source_approved_proposal_bundle_id="gate2-1",
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="gate2-route-1",
        timeline_run_id="timeline-run-1",
        gate3_review_id="gate3-review-1",
        gate3_route_id="gate3-route-1",
        evidence_refs=[EVIDENCE],
        created_at=NOW,
    )


@pytest.fixture()
def freeze_setup(
    tmp_path: Path,
) -> tuple[
    StoryBibleFreezeService,
    StoryBibleProductionRunV1,
    RecordingCommitService,
    StoryBibleReviewRepository,
]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'freeze.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    storybible = StoryBibleRepository(session)
    reviews = StoryBibleReviewRepository(session)
    proposal = _proposal()
    prior_hash = canonical_storybible_snapshot_hash(
        StoryBibleCanonicalSnapshotV1(project_id="project-1")
    )
    production = StoryBibleProductionRunV1(
        run_id="run-1",
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=prior_hash,
        input_hash="input-hash-1",
        model_identity="mock-model",
        status="SUCCEEDED",
        curator_proposal=proposal,
        agent_run_id="agent-run-1",
        provider_request_count=1,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(
        StoryBibleProductionRunModel(
            run_id=production.run_id,
            project_id=production.project_id,
            gate2_approved_bundle_id=production.gate2_approved_bundle_id,
            approved_timeline_bundle_id=production.approved_timeline_bundle_id,
            input_hash=production.input_hash,
            status=str(production.status),
            payload=production.model_dump(mode="json"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    context = StoryBibleReviewContextV1(
        review_id="review-1",
        project_id="project-1",
        source_storybible_run_id="run-1",
        source_approved_timeline_bundle_id="timeline-1",
        canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
        canonical_snapshot_hash=prior_hash,
        proposal_hash=storybible_proposal_hash(proposal),
        reviewed_at=NOW,
    )
    result = StoryBibleReviewService(ChunkLookup()).review(
        context,
        production_run=production,
        proposal=proposal,
        commit_plan=proposal.commit_plan,
        approved_timeline=_timeline(),
    )
    reviews.save_review(context, result)
    commit = RecordingCommitService()
    service = StoryBibleFreezeService(
        review_repository=reviews,
        storybible_repository=storybible,
        commit_service=commit,
        clock=lambda: FROZEN_AT,
    )
    return service, production, commit, reviews


def test_real_review_lifecycle_persists_service_result(
    freeze_setup: tuple[
        StoryBibleFreezeService,
        StoryBibleProductionRunV1,
        RecordingCommitService,
        StoryBibleReviewRepository,
    ],
) -> None:
    _, _, _, reviews = freeze_setup
    persisted = reviews.get_review("review-1")

    assert persisted is not None
    assert persisted.review_result.decision == "APPROVE"
    assert persisted.canonical_snapshot.profiles == []


def test_freeze_hash_is_stable_and_commit_service_is_the_only_write_entry(
    freeze_setup: tuple[
        StoryBibleFreezeService,
        StoryBibleProductionRunV1,
        RecordingCommitService,
        StoryBibleReviewRepository,
    ],
) -> None:
    service, production, commit, _ = freeze_setup

    first = service.freeze("review-1", production_run=production, approved_timeline=_timeline())
    replay = service.freeze("review-1", production_run=production, approved_timeline=_timeline())

    assert replay == first
    assert first.snapshot_hash == replay.snapshot_hash
    assert [entity.profile_id for entity in first.entities] == ["profile-1"]
    assert commit.calls == 1


def test_frozen_bundle_is_immutable(
    freeze_setup: tuple[
        StoryBibleFreezeService,
        StoryBibleProductionRunV1,
        RecordingCommitService,
        StoryBibleReviewRepository,
    ],
) -> None:
    service, production, _, reviews = freeze_setup
    bundle = service.freeze(
        "review-1", production_run=production, approved_timeline=_timeline()
    )

    with pytest.raises(ValueError, match="immutable"):
        reviews.freeze("review-1", bundle.model_copy(update={"snapshot_hash": "changed"}))


def test_freeze_recovery_after_checkpoint_failure(
    freeze_setup: tuple[
        StoryBibleFreezeService,
        StoryBibleProductionRunV1,
        RecordingCommitService,
        StoryBibleReviewRepository,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, production, commit, reviews = freeze_setup
    persist = reviews.freeze
    failed = False

    def fail_once(
        review_id: str, bundle: ApprovedStoryBibleBundleV1
    ) -> StoryBibleReviewRunV1:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("checkpoint unavailable")
        return persist(review_id, bundle)

    monkeypatch.setattr(reviews, "freeze", fail_once)
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        service.freeze(
            "review-1", production_run=production, approved_timeline=_timeline()
        )

    recovered = service.freeze(
        "review-1", production_run=production, approved_timeline=_timeline()
    )
    assert recovered.entities[0].profile_id == "profile-1"
    assert commit.calls == 1
