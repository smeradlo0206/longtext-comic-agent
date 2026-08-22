"""Contracts for deterministic StoryBible review and immutable freeze payloads."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleReviewIssueV1,
    StoryBibleReviewMetadataV1,
    StoryBibleReviewResultV1,
    StoryBibleReviewRunV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
)

EVIDENCE = EvidenceRefV1(chunk_id="chunk-1", quote_text="Xia Ming arrived.")


def _approved_review() -> StoryBibleReviewResultV1:
    return StoryBibleReviewResultV1(
        review_id="review-1",
        project_id="project-1",
        storybible_run_id="run-1",
        proposal_hash="proposal-hash-1",
        decision="APPROVE",
        evidence_checks=[],
        validated_entities=["profile-1", "profile-2"],
        validated_relationships=["relationship-1"],
        validated_world_rules=[],
        reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def _bundle(frozen_at: datetime) -> ApprovedStoryBibleBundleV1:
    entities = [
        StoryEntityProfileV1(
            profile_id=profile_id,
            project_id="project-1",
            entity_kind="PERSON",
            canonical_name=name,
            evidence_refs=[EVIDENCE],
        )
        for profile_id, name in (("profile-1", "Xia Ming"), ("profile-2", "Lin Yue"))
    ]
    return ApprovedStoryBibleBundleV1(
        bundle_id="bundle-1",
        project_id="project-1",
        source_storybible_run_id="run-1",
        snapshot_hash="snapshot-hash-1",
        entities=entities,
        relationships=[
            StoryRelationshipV1(
                relationship_id="relationship-1",
                project_id="project-1",
                source_profile_id="profile-1",
                target_profile_id="profile-2",
                relationship_type="FRIEND",
                evidence_refs=[EVIDENCE],
            )
        ],
        state_changes=[
            StoryEntityStateV1(
                state_id="state-1",
                project_id="project-1",
                profile_id="profile-1",
                state={"location": "school"},
                evidence_refs=[EVIDENCE],
            )
        ],
        evidence_refs=[EVIDENCE],
        review_metadata=StoryBibleReviewMetadataV1(
            review_id="review-1",
            decision="APPROVE",
            proposal_hash="proposal-hash-1",
            source_approved_timeline_bundle_id="timeline-bundle-1",
            reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
            frozen_at=frozen_at,
        ),
    )


def test_review_result_supports_required_decisions_and_validated_ids() -> None:
    assert _approved_review().decision == "APPROVE"
    with pytest.raises(ValidationError, match="unique and sorted"):
        StoryBibleReviewResultV1.model_validate(
            _approved_review().model_dump()
            | {"validated_entities": ["profile-2", "profile-1"]}
        )


def test_review_decision_must_match_structured_issues() -> None:
    issue = StoryBibleReviewIssueV1(
        issue_id="issue-1",
        category="EVIDENCE_INVALID",
        severity="BLOCKING",
        message="Evidence does not resolve.",
        affected_ids=["profile-1"],
    )
    rejected = StoryBibleReviewResultV1.model_validate(
        _approved_review().model_dump() | {"decision": "REJECT", "issues": [issue]}
    )
    assert rejected.decision == "REJECT"
    with pytest.raises(ValidationError, match="APPROVE review cannot contain issues"):
        StoryBibleReviewResultV1.model_validate(
            _approved_review().model_dump() | {"issues": [issue]}
        )


def test_approved_bundle_uses_entities_and_enforces_closed_references() -> None:
    frozen_at = datetime(2026, 8, 23, 1, tzinfo=UTC)
    bundle = _bundle(frozen_at)

    assert "entities" in bundle.model_dump()
    assert "characters" not in bundle.model_dump()
    with pytest.raises(ValidationError, match="bundled entities"):
        ApprovedStoryBibleBundleV1.model_validate(
            bundle.model_dump()
            | {
                "entities": [bundle.entities[0].model_dump()],
            }
        )


def test_review_run_requires_approved_bundle_only_when_frozen() -> None:
    reviewed = StoryBibleReviewRunV1(
        review_id="review-1",
        project_id="project-1",
        source_storybible_run_id="run-1",
        source_approved_timeline_bundle_id="timeline-bundle-1",
        canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
        canonical_snapshot_hash="canonical-snapshot-hash-1",
        proposal_hash="proposal-hash-1",
        review_result=_approved_review(),
    )
    frozen_at = datetime(2026, 8, 23, 1, tzinfo=UTC)
    frozen = StoryBibleReviewRunV1.model_validate(
        reviewed.model_dump()
        | {
            "status": "FROZEN",
            "approved_bundle": _bundle(frozen_at).model_dump(),
            "frozen_at": frozen_at,
            "updated_at": frozen_at,
        }
    )

    assert frozen.status == "FROZEN"
    with pytest.raises(ValidationError, match="only an APPROVE review may be frozen"):
        StoryBibleReviewRunV1.model_validate(
            frozen.model_dump()
            | {
                "review_result": frozen.review_result.model_copy(
                    update={"decision": "REJECT"}
                ).model_dump()
                | {
                    "issues": [
                        {
                            "issue_id": "issue-1",
                            "category": "CONFLICT",
                            "severity": "BLOCKING",
                            "message": "Conflict.",
                        }
                    ]
                }
            }
        )
