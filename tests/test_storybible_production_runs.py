"""Production StoryBible input identity and durable checkpoint contracts."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.database.models import (
    NarrativeAnalysisRunModel,
    StoryBibleProductionRunModel,
    TimelineGate3RunModel,
)
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.review import ApprovedProposalBundleV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    ProfileUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionFailureStage,
    StoryBibleProductionInputV1,
    StoryBibleProductionRunStatus,
    StoryEntityProfileV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1, TimelineGate3RunStatus
from comic_agent.services.storybible_production_identity import (
    storybible_production_input_hash,
)

EVIDENCE = [EvidenceRefV1(chunk_id="chunk-1", quote_text="Xia Ming arrived.")]


def _production_input(
    *,
    project_id: str = "project-1",
    gate2_bundle_id: str = "gate2-bundle-1",
    timeline_bundle_id: str = "timeline-bundle-1",
    snapshot_hash: str = "snapshot-hash-1",
) -> StoryBibleProductionInputV1:
    return StoryBibleProductionInputV1(
        project_id=project_id,
        gate2_approved_bundle_id=gate2_bundle_id,
        approved_timeline_bundle_id=timeline_bundle_id,
        canonical_storybible_snapshot_hash=snapshot_hash,
    )


def _approved_gate2_bundle(
    *, project_id: str = "project-1", bundle_id: str = "gate2-bundle-1"
) -> ApprovedProposalBundleV1:
    return ApprovedProposalBundleV1(
        bundle_id=bundle_id,
        project_id=project_id,
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="gate2-review-1",
        policy_id="gate2-policy-1",
    )


def _approved_timeline_bundle(
    *,
    project_id: str = "project-1",
    bundle_id: str = "timeline-bundle-1",
    gate2_bundle_id: str = "gate2-bundle-1",
) -> ApprovedTimelineBundleV1:
    return ApprovedTimelineBundleV1(
        bundle_id=bundle_id,
        project_id=project_id,
        source_approved_proposal_bundle_id=gate2_bundle_id,
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="analysis-1",
        timeline_run_id="timeline-run-1",
        gate3_review_id="gate3-review-1",
        gate3_route_id="gate3-route-1",
        evidence_refs=EVIDENCE,
    )


def _persist_lineage(
    session: Session,
    *,
    gate2: ApprovedProposalBundleV1 | None = None,
    timeline: ApprovedTimelineBundleV1 | None = None,
) -> None:
    gate2 = gate2 or _approved_gate2_bundle()
    timeline = timeline or _approved_timeline_bundle(
        project_id=gate2.project_id, gate2_bundle_id=gate2.bundle_id
    )
    now = datetime.now(UTC)
    session.add(
        NarrativeAnalysisRunModel(
            analysis_run_id=gate2.analysis_run_id,
            project_id=gate2.project_id,
            document_id=gate2.document_id,
            status="SUCCEEDED",
            payload={
                "review_gate2_route": {
                    "approved_proposal_bundle": gate2.model_dump(mode="json")
                }
            },
            result_payload=None,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        TimelineGate3RunModel(
            timeline_run_id=timeline.timeline_run_id,
            project_id=timeline.project_id,
            source_bundle_id=timeline.source_approved_proposal_bundle_id,
            idempotency_key=f"key-{timeline.timeline_run_id}",
            status=str(TimelineGate3RunStatus.APPROVED),
            payload={"approved_timeline_bundle": timeline.model_dump(mode="json")},
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


@pytest.fixture()
def production_repository(tmp_path: Path) -> tuple[StoryBibleProductionRunRepository, Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'storybible-production.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    _persist_lineage(session)
    return StoryBibleProductionRunRepository(session), session


def _curator_proposal() -> StoryBibleCuratorProposalV1:
    profile = StoryEntityProfileV1(
        profile_id="profile-1",
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name="Xia Ming",
        evidence_refs=EVIDENCE,
    )
    update = ProfileUpdateProposalV1(
        update_id="update-1",
        project_id="project-1",
        profile=profile,
        evidence_refs=EVIDENCE,
    )
    plan = CommitPlanV1(
        commit_plan_id="plan-1",
        project_id="project-1",
        source_proposal_id="proposal-1",
        content_hash="provider-content-hash",
        updates=[update],
        evidence_refs=EVIDENCE,
    )
    conflict = ConflictV1(
        conflict_id="conflict-1",
        project_id="project-1",
        category="IDENTITY",
        summary="Two aliases may refer to one person.",
        affected_update_ids=["update-1"],
        evidence_refs=EVIDENCE,
    )
    return StoryBibleCuratorProposalV1(
        proposal_id="proposal-1",
        project_id="project-1",
        commit_plan=plan,
        conflicts=[conflict],
        evidence_refs=EVIDENCE,
        confidence=0.8,
    )


def test_production_input_is_strict_and_contains_no_proposal_arrays() -> None:
    value = _production_input()

    assert set(value.model_dump()) == {
        "schema_version",
        "project_id",
        "gate2_approved_bundle_id",
        "approved_timeline_bundle_id",
        "canonical_storybible_snapshot_hash",
    }
    with pytest.raises(ValidationError):
        StoryBibleProductionInputV1.model_validate(
            value.model_dump() | {"event_proposals": []}
        )
    with pytest.raises(ValidationError):
        _production_input(project_id=" ")
    with pytest.raises(ValidationError):
        _production_input(gate2_bundle_id="x" * 129)


def test_input_hash_is_canonical_and_changes_with_material_identity() -> None:
    value = _production_input()
    reordered = StoryBibleProductionInputV1.model_validate(
        dict(reversed(list(value.model_dump().items())))
    )
    expected = storybible_production_input_hash(value, model_identity="curator-model-v1")

    assert storybible_production_input_hash(
        reordered, model_identity="curator-model-v1"
    ) == expected
    assert storybible_production_input_hash(
        _production_input(gate2_bundle_id="gate2-bundle-2"),
        model_identity="curator-model-v1",
    ) != expected
    assert storybible_production_input_hash(
        _production_input(timeline_bundle_id="timeline-bundle-2"),
        model_identity="curator-model-v1",
    ) != expected
    assert storybible_production_input_hash(value, model_identity="curator-model-v2") != expected


def test_reservation_is_idempotent_and_material_changes_get_new_runs(
    production_repository: tuple[StoryBibleProductionRunRepository, Session],
) -> None:
    repository, session = production_repository
    first = repository.reserve_run(_production_input(), model_identity="curator-model-v1")
    duplicate = repository.reserve_run(_production_input(), model_identity="curator-model-v1")
    changed = repository.reserve_run(
        _production_input(snapshot_hash="snapshot-hash-2"),
        model_identity="curator-model-v1",
    )

    assert duplicate.run_id == first.run_id
    assert changed.run_id != first.run_id
    assert session.scalar(select(func.count()).select_from(StoryBibleProductionRunModel)) == 2


def test_legal_transitions_and_full_proposal_round_trip(
    production_repository: tuple[StoryBibleProductionRunRepository, Session],
) -> None:
    repository, _ = production_repository
    reserved = repository.reserve_run(_production_input(), model_identity="curator-model-v1")
    running = repository.mark_running(reserved.run_id)
    succeeded = repository.save_success(
        running.run_id,
        curator_proposal=_curator_proposal(),
        agent_run_id="storybible-agent-run-1",
    )
    restored = repository.get_run(succeeded.run_id)

    assert restored is not None
    assert restored.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert restored.curator_proposal == _curator_proposal()
    assert restored.curator_proposal.conflicts[0].conflict_id == "conflict-1"
    assert restored.curator_proposal.commit_plan.updates[0].update_id == "update-1"
    with pytest.raises(ValueError, match="illegal StoryBible run transition"):
        repository.save_failure(succeeded.run_id, error_message="must not overwrite")


def test_running_can_transition_to_failed(
    production_repository: tuple[StoryBibleProductionRunRepository, Session],
) -> None:
    repository, _ = production_repository
    run = repository.reserve_run(_production_input(), model_identity="curator-model-v1")
    repository.mark_running(run.run_id)

    failed = repository.save_failure(run.run_id, error_message="sanitized failure")

    assert failed.status == StoryBibleProductionRunStatus.FAILED
    with pytest.raises(ValueError, match="illegal StoryBible run transition"):
        repository.mark_running(run.run_id)


def test_atomic_claim_has_one_winner_and_failed_run_may_link_terminal_agent_run(
    production_repository: tuple[StoryBibleProductionRunRepository, Session],
) -> None:
    repository, _ = production_repository
    run = repository.reserve_run(_production_input(), model_identity="curator-model-v1")

    assert repository.claim_execution(run.run_id) is True
    assert repository.claim_execution(run.run_id) is False
    failed = repository.save_failure(
        run.run_id,
        error_message="sanitized failure",
        failure_stage=StoryBibleProductionFailureStage.PROVIDER,
        agent_run_id="storybible-agent-run-1",
    )

    assert failed.provider_request_count == 1
    assert failed.failure_stage == StoryBibleProductionFailureStage.PROVIDER
    assert failed.agent_run_id == "storybible-agent-run-1"


@pytest.mark.parametrize("wrong_artifact", ["gate2-project", "timeline-project", "lineage"])
def test_reservation_rejects_cross_project_or_unrelated_lineage(
    tmp_path: Path, wrong_artifact: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / f'{wrong_artifact}.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    gate2 = _approved_gate2_bundle(
        project_id="project-2" if wrong_artifact == "gate2-project" else "project-1"
    )
    timeline = _approved_timeline_bundle(
        project_id="project-2" if wrong_artifact == "timeline-project" else "project-1",
        gate2_bundle_id=("gate2-unrelated" if wrong_artifact == "lineage" else gate2.bundle_id),
    )
    _persist_lineage(session, gate2=gate2, timeline=timeline)
    repository = StoryBibleProductionRunRepository(session)

    with pytest.raises(ValueError):
        repository.reserve_run(_production_input(), model_identity="curator-model-v1")
