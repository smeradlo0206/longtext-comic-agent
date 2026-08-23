"""Core contracts for explicit human resolution of a held Gate 3 run."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.main import create_app
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.timeline import (
    Gate3HumanReviewInputV1,
    Gate3HumanReviewResolution,
    Gate3HumanReviewV1,
    ReviewGate3Decision,
    ReviewGate3ResultV1,
    TimelineAnalysisInputV1,
    TimelineAnalysisProposalV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
)
from comic_agent.services.gate3_human_review_service import Gate3HumanReviewService
from comic_agent.services.review_gate3_service import ReviewGate3Service


def _held_run(run_id: str = "timeline-run-1") -> TimelineGate3RunV1:
    evidence = EvidenceRefV1(chunk_id="chunk-1", quote_text="The order is unclear.")
    events = [
        EventProposalV1(
            proposal_id=event_id,
            event_type="EVENT",
            summary=f"Event {event_id}",
            participant_ids=[],
            evidence_refs=[evidence],
            confidence=0.8,
            reality_layer=RealityLayer.PRIMARY,
        )
        for event_id in ("event-1", "event-2")
    ]
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1",
        source_event_id="event-1",
        target_event_id="event-2",
        relation="UNKNOWN",
        confidence=0.0,
    )
    timeline_input = TimelineAnalysisInputV1(
        schema_version="1.3",
        project_id="project-1",
        source_approved_bundle_id="gate2-bundle-1",
        source_review_run_id="gate2-review-1",
        event_proposals=events,
    )
    proposal = TimelineAnalysisProposalV1(
        proposal_id="timeline-proposal-1",
        project_id="project-1",
        temporal_relations=[relation],
        evidence_refs=[evidence],
        confidence=0.5,
    )
    result, route = ReviewGate3Service().review(
        project_id="project-1",
        source_approved_proposal_bundle_id="gate2-bundle-1",
        timeline_run_id=run_id,
        reviewer_agent_run_id="automated-gate3-review-1",
        event_ids=[event.proposal_id for event in events],
        temporal_relations=[relation],
        evidence_refs=[evidence],
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="gate2-route-1",
    )
    return TimelineGate3RunV1(
        timeline_run_id=run_id,
        project_id="project-1",
        source_approved_proposal_bundle_id="gate2-bundle-1",
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="gate2-route-1",
        idempotency_key=f"key-{run_id}",
        status=TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
        timeline_input=timeline_input,
        timeline_proposal=proposal,
        timeline_agent_run_id="timeline-agent-run-1",
        gate3_result=result,
        gate3_route=route,
        provider_request_count=1,
    )


def _repository(tmp_path: Path) -> TimelineGate3Repository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'human-review.db'}")
    Base.metadata.create_all(engine)
    return TimelineGate3Repository(Session(engine))


def _input(
    resolution: Gate3HumanReviewResolution = Gate3HumanReviewResolution.APPROVE,
    *,
    reviewer_id: str = "reviewer-1",
    note: str | None = "Reviewed against the source.",
) -> Gate3HumanReviewInputV1:
    return Gate3HumanReviewInputV1(
        gate3_run_id="timeline-run-1",
        resolution=resolution,
        reviewer_id=reviewer_id,
        note=note,
    )


@pytest.mark.parametrize(
    "resolution",
    [Gate3HumanReviewResolution.APPROVE, Gate3HumanReviewResolution.REJECT],
)
def test_human_review_input_accepts_only_final_resolutions(
    resolution: Gate3HumanReviewResolution,
) -> None:
    assert _input(resolution).resolution == resolution


def test_human_review_input_rejects_automated_state_names() -> None:
    with pytest.raises(ValidationError):
        Gate3HumanReviewInputV1(
            gate3_run_id="timeline-run-1",
            resolution="NEEDS_HUMAN_REVIEW",
            reviewer_id="reviewer-1",
        )


def test_legacy_gate3_result_without_human_fields_still_parses() -> None:
    result = _held_run().gate3_result
    assert result is not None
    payload = result.model_dump(exclude={"human_review", "effective_decision"})
    parsed = ReviewGate3ResultV1.model_validate(payload)

    assert parsed.human_review is None
    assert parsed.effective_decision is None


@pytest.mark.parametrize(
    ("resolution", "expected_status"),
    [
        (Gate3HumanReviewResolution.APPROVE, TimelineGate3RunStatus.APPROVED),
        (Gate3HumanReviewResolution.REJECT, TimelineGate3RunStatus.REJECTED),
    ],
)
def test_service_resolves_held_run_and_preserves_automated_result(
    tmp_path: Path,
    resolution: Gate3HumanReviewResolution,
    expected_status: TimelineGate3RunStatus,
) -> None:
    repository = _repository(tmp_path)
    original = repository.reserve_run(_held_run())

    resolved = Gate3HumanReviewService(repository).review_gate3_run(_input(resolution))

    assert resolved.status == expected_status
    assert resolved.gate3_result is not None
    assert original.gate3_result is not None
    assert resolved.gate3_result.decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
    assert resolved.gate3_result.issues == original.gate3_result.issues
    assert resolved.gate3_result.reviewer_agent_run_id == "automated-gate3-review-1"
    assert resolved.gate3_result.effective_decision == str(expected_status)
    assert resolved.gate3_result.human_review is not None
    assert resolved.gate3_result.human_review.reviewer_id == "reviewer-1"
    assert resolved.gate3_result.human_review.note == "Reviewed against the source."
    assert resolved.gate3_result.human_review.reviewed_at.tzinfo == UTC
    if resolution == Gate3HumanReviewResolution.APPROVE:
        assert resolved.approved_timeline_bundle is not None
        assert resolved.approved_timeline_bundle.timeline_run_id == resolved.timeline_run_id
    else:
        assert resolved.approved_timeline_bundle is None
    assert resolved.provider_request_count == 1


def test_service_missing_run_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        Gate3HumanReviewService(_repository(tmp_path)).review_gate3_run(_input())


@pytest.mark.parametrize(
    "status",
    [
        TimelineGate3RunStatus.RESERVED,
        TimelineGate3RunStatus.APPROVED,
        TimelineGate3RunStatus.REJECTED,
        TimelineGate3RunStatus.FAILED,
    ],
)
def test_service_rejects_runs_not_awaiting_human_review(
    tmp_path: Path,
    status: TimelineGate3RunStatus,
) -> None:
    repository = _repository(tmp_path)
    held = _held_run()
    payload = held.model_dump() | {"status": status}
    if status == TimelineGate3RunStatus.APPROVED:
        assert held.timeline_proposal is not None
        payload["approved_timeline_bundle"] = ReviewGate3Service.build_approved_bundle(
            decision=ReviewGate3Decision.APPROVED,
            route_id="route-1",
            review_id="review-1",
            project_id="project-1",
            source_bundle_id="gate2-bundle-1",
            source_gate2_review_id="gate2-review-1",
            source_gate2_route_id="gate2-route-1",
            timeline_run_id="timeline-run-1",
            relations=[],
            event_ids=["event-1", "event-2"],
            evidence=held.timeline_proposal.evidence_refs,
        )
    run = TimelineGate3RunV1.model_validate(payload)
    repository.reserve_run(run)

    with pytest.raises(ValueError, match="not awaiting human review"):
        Gate3HumanReviewService(repository).review_gate3_run(_input())


def test_identical_repeat_is_idempotent_and_conflicting_repeat_is_rejected(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.reserve_run(_held_run())
    service = Gate3HumanReviewService(repository)
    first = service.review_gate3_run(_input())

    repeated = service.review_gate3_run(_input())
    assert repeated == first
    with pytest.raises(ValueError, match="not awaiting human review"):
        service.review_gate3_run(_input(Gate3HumanReviewResolution.REJECT))


def test_repository_human_transition_is_conditional_and_generic_transition_stays_guarded(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    held = repository.reserve_run(_held_run())
    now = datetime.now(UTC)
    metadata = Gate3HumanReviewV1(
        **_input().model_dump(),
        reviewed_at=now,
        final_decision=ReviewGate3Decision.APPROVED,
    )
    assert held.gate3_result is not None
    resolved_result = held.gate3_result.model_copy(
        update={"human_review": metadata, "effective_decision": ReviewGate3Decision.APPROVED}
    )
    approved = TimelineGate3RunV1.model_validate(
        held.model_dump()
        | {
            "status": TimelineGate3RunStatus.APPROVED,
            "gate3_result": resolved_result,
            "updated_at": now,
        }
    )

    assert repository.apply_human_review(approved) is True
    assert repository.apply_human_review(approved) is False
    rejected_attempt = approved.model_copy(update={"status": TimelineGate3RunStatus.REJECTED})
    assert repository.save_transition(rejected_attempt).status == TimelineGate3RunStatus.APPROVED


def test_repository_rejects_inappropriate_human_review_target(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="must resolve"):
        repository.apply_human_review(_held_run())


def _api_with_run(tmp_path: Path, run: TimelineGate3RunV1 | None = None):  # type: ignore[no-untyped-def]
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'human-review-api.db'}")
    session = app.state.session_factory()
    try:
        TimelineGate3Repository(session).reserve_run(run or _held_run())
    finally:
        session.close()
    return app


def _review_payload(resolution: str = "APPROVE") -> dict[str, str]:
    return {
        "resolution": resolution,
        "reviewer_id": "reviewer-1",
        "note": "Reviewed against the source.",
    }


def _review_path(run_id: str = "timeline-run-1", project_id: str = "project-1") -> str:
    return f"/projects/{project_id}/timeline-gate3/runs/{run_id}/review"


def test_http_approval_finalizes_canonical_bundle_with_exact_lineage(tmp_path: Path) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(_review_path(), json=_review_payload())
        approved = client.get(
            "/projects/project-1/timeline-gate3/gate2-bundle-1/approved-bundle"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["automated_decision"] == "NEEDS_HUMAN_REVIEW"
    assert body["effective_decision"] == "APPROVED"
    assert body["human_review"]["reviewer_id"] == "reviewer-1"
    assert body["approved_timeline_bundle_available"] is True
    assert approved.status_code == 200
    assert approved.json()["bundle_id"] == body["approved_timeline_bundle_id"]
    assert approved.json()["timeline_run_id"] == "timeline-run-1"
    assert approved.json()["source_approved_proposal_bundle_id"] == "gate2-bundle-1"
    assert approved.json()["temporal_relations"][0]["proposal_id"] == "relation-1"


def test_http_rejection_persists_no_bundle(tmp_path: Path) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(_review_path(), json=_review_payload("REJECT"))
        approved = client.get(
            "/projects/project-1/timeline-gate3/gate2-bundle-1/approved-bundle"
        )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert response.json()["effective_decision"] == "REJECTED"
    assert response.json()["approved_timeline_bundle_available"] is False
    assert approved.status_code == 409


def test_http_unknown_or_wrong_project_run_is_not_found(tmp_path: Path) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        missing = client.post(_review_path("missing"), json=_review_payload())
        wrong_project = client.post(
            _review_path(project_id="project-2"),
            json=_review_payload(),
        )

    assert missing.status_code == 404
    assert wrong_project.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"resolution": "NEEDS_HUMAN_REVIEW", "reviewer_id": "reviewer-1"},
        {"resolution": "APPROVE"},
        {"resolution": "APPROVE", "reviewer_id": ""},
    ],
)
def test_http_invalid_review_body_is_rejected(tmp_path: Path, payload: dict[str, str]) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(_review_path(), json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "status",
    [TimelineGate3RunStatus.RESERVED, TimelineGate3RunStatus.FAILED],
)
def test_http_nonreviewable_run_is_a_conflict(
    tmp_path: Path,
    status: TimelineGate3RunStatus,
) -> None:
    run = _held_run().model_copy(update={"status": status})
    app = _api_with_run(tmp_path, run)

    with TestClient(app) as client:
        response = client.post(_review_path(), json=_review_payload())

    assert response.status_code == 409


@pytest.mark.parametrize("resolution", ["APPROVE", "REJECT"])
def test_http_identical_review_is_idempotent(tmp_path: Path, resolution: str) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        first = client.post(_review_path(), json=_review_payload(resolution))
        second = client.post(_review_path(), json=_review_payload(resolution))

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()


def test_http_conflicting_second_review_is_rejected(tmp_path: Path) -> None:
    app = _api_with_run(tmp_path)

    with TestClient(app) as client:
        first = client.post(_review_path(), json=_review_payload())
        conflict = client.post(_review_path(), json=_review_payload("REJECT"))

    assert first.status_code == 200
    assert conflict.status_code == 409


def test_http_resumes_human_approved_run_missing_its_bundle(tmp_path: Path) -> None:
    held = _held_run()
    assert held.gate3_result is not None
    reviewed_at = datetime.now(UTC)
    human_review = Gate3HumanReviewV1(
        **_input().model_dump(),
        reviewed_at=reviewed_at,
        final_decision=ReviewGate3Decision.APPROVED,
    )
    approved_without_bundle = TimelineGate3RunV1.model_validate(
        held.model_dump()
        | {
            "status": TimelineGate3RunStatus.APPROVED,
            "gate3_result": held.gate3_result.model_copy(
                update={
                    "human_review": human_review,
                    "effective_decision": ReviewGate3Decision.APPROVED,
                }
            ),
        }
    )
    app = _api_with_run(tmp_path, approved_without_bundle)

    with TestClient(app) as client:
        response = client.post(_review_path(), json=_review_payload())

    assert response.status_code == 200
    assert response.json()["approved_timeline_bundle_available"] is True
    assert response.json()["human_review"]["reviewed_at"] == reviewed_at.isoformat().replace(
        "+00:00", "Z"
    )
