"""Deterministic StoryBible proposal review without model calls."""

from datetime import UTC, datetime

import pytest

from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionRunV1,
    StoryBibleReviewContextV1,
    StoryBibleReviewResultV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)
from comic_agent.services.storybible_review_service import StoryBibleReviewService

NOW = datetime(2026, 8, 23, tzinfo=UTC)
TEXT = "Xia Ming arrived at school and greeted Lin Yue."
EVIDENCE = EvidenceRefV1(
    chunk_id="chunk-1",
    quote_start=0,
    quote_end=8,
    quote_text="Xia Ming",
)


class ChunkLookup:
    def __init__(self, chunk: SourceChunkV1 | None) -> None:
        self.chunk = chunk

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        if self.chunk is not None and self.chunk.chunk_id == chunk_id:
            return self.chunk
        return None


def _chunk(*, project_id: str = "project-1") -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id="chunk-1",
        project_id=project_id,
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text=TEXT,
        checksum="checksum-1",
    )


def _profile(profile_id: str, name: str) -> StoryEntityProfileV1:
    return StoryEntityProfileV1(
        profile_id=profile_id,
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name=name,
        evidence_refs=[EVIDENCE],
    )


def _proposal(
    *,
    relationships: list[StoryRelationshipV1] | None = None,
    state_event_id: str = "event-1",
    conflicts: list[ConflictV1] | None = None,
    evidence: EvidenceRefV1 = EVIDENCE,
) -> StoryBibleCuratorProposalV1:
    profiles = [_profile("profile-1", "Xia Ming"), _profile("profile-2", "Lin Yue")]
    relationship_values = relationships or [
        StoryRelationshipV1(
            relationship_id="relationship-1",
            project_id="project-1",
            source_profile_id="profile-1",
            target_profile_id="profile-2",
            relationship_type="FRIEND",
            attributes={"status": "friendly"},
            valid_from_event_id="event-1",
            valid_from_order=0,
            evidence_refs=[evidence],
        )
    ]
    updates = [
        *[
            ProfileUpdateProposalV1(
                update_id=f"update-{profile.profile_id}",
                project_id="project-1",
                profile=profile.model_copy(update={"evidence_refs": [evidence]}),
                evidence_refs=[evidence],
            )
            for profile in profiles
        ],
        *[
            RelationshipUpdateProposalV1(
                update_id=f"update-{relationship.relationship_id}",
                project_id="project-1",
                relationship=relationship.model_copy(update={"evidence_refs": [evidence]}),
                evidence_refs=[evidence],
            )
            for relationship in relationship_values
        ],
        StateUpdateProposalV1(
            update_id="update-state-1",
            project_id="project-1",
            state=StoryEntityStateV1(
                state_id="state-1",
                project_id="project-1",
                profile_id="profile-1",
                state={"location": "school"},
                valid_from_event_id=state_event_id,
                valid_from_order=0,
                evidence_refs=[evidence],
            ),
            evidence_refs=[evidence],
        ),
        WorldRuleUpdateProposalV1(
            update_id="update-rule-1",
            project_id="project-1",
            world_rule=WorldRuleV1(
                rule_id="rule-1",
                project_id="project-1",
                name="School access",
                statement="Students may enter the school.",
                scope="school",
                evidence_refs=[evidence],
            ),
            evidence_refs=[evidence],
        ),
    ]
    plan = CommitPlanV1(
        commit_plan_id="plan-1",
        project_id="project-1",
        source_proposal_id="proposal-1",
        content_hash="content-hash-1",
        updates=updates,
        evidence_refs=[evidence],
    )
    return StoryBibleCuratorProposalV1(
        proposal_id="proposal-1",
        project_id="project-1",
        commit_plan=plan,
        conflicts=conflicts or [],
        evidence_refs=[evidence],
        confidence=0.9,
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
        event_ids=["event-1"],
        evidence_refs=[EVIDENCE],
        created_at=NOW,
    )


def _inputs(
    proposal: StoryBibleCuratorProposalV1,
    snapshot: StoryBibleCanonicalSnapshotV1 | None = None,
) -> tuple[StoryBibleReviewContextV1, StoryBibleProductionRunV1]:
    proposal_hash = storybible_proposal_hash(proposal)
    snapshot = snapshot or StoryBibleCanonicalSnapshotV1(project_id="project-1")
    snapshot_hash = canonical_storybible_snapshot_hash(snapshot)
    context = StoryBibleReviewContextV1(
        review_id="review-1",
        project_id="project-1",
        source_storybible_run_id="run-1",
        source_approved_timeline_bundle_id="timeline-1",
        canonical_snapshot=snapshot,
        canonical_snapshot_hash=snapshot_hash,
        proposal_hash=proposal_hash,
        reviewed_at=NOW,
    )
    production = StoryBibleProductionRunV1(
        run_id="run-1",
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=snapshot_hash,
        input_hash="input-hash-1",
        model_identity="mock-model",
        status="SUCCEEDED",
        curator_proposal=proposal,
        agent_run_id="agent-run-1",
        provider_request_count=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return context, production


def _review(
    proposal: StoryBibleCuratorProposalV1,
    *,
    lookup: ChunkLookup | None = None,
    snapshot: StoryBibleCanonicalSnapshotV1 | None = None,
) -> StoryBibleReviewResultV1:
    context, production = _inputs(proposal, snapshot)
    return StoryBibleReviewService(lookup or ChunkLookup(_chunk())).review(
        context,
        production_run=production,
        proposal=proposal,
        commit_plan=proposal.commit_plan,
        approved_timeline=_timeline(),
    )


def test_clean_proposal_is_approved() -> None:
    result = _review(_proposal())

    assert result.decision == "APPROVE"
    assert result.issues == []
    assert result.validated_entities == ["profile-1", "profile-2"]
    assert result.validated_relationships == ["relationship-1"]
    assert result.validated_world_rules == ["rule-1"]
    assert result.evidence_checks
    assert all(check.valid for check in result.evidence_checks)


def test_invalid_evidence_is_rejected() -> None:
    invalid = EvidenceRefV1(chunk_id="missing", quote_text="fabricated")
    result = _review(_proposal(evidence=invalid))

    assert result.decision == "REJECT"
    assert {issue.category for issue in result.issues} == {"INVALID_EVIDENCE"}
    assert any(not check.valid for check in result.evidence_checks)


def test_overlapping_incompatible_relationships_are_rejected() -> None:
    relationships = [
        StoryRelationshipV1(
            relationship_id=f"relationship-{index}",
            project_id="project-1",
            source_profile_id="profile-1",
            target_profile_id="profile-2",
            relationship_type="ALLY",
            attributes={"trust": trust},
            valid_from_order=0,
            valid_until_order=2,
            evidence_refs=[EVIDENCE],
        )
        for index, trust in ((1, "HIGH"), (2, "LOW"))
    ]
    result = _review(_proposal(relationships=relationships))

    assert result.decision == "REJECT"
    assert "RELATIONSHIP_CONFLICT" in {issue.category for issue in result.issues}


def test_unknown_semantic_conflict_requires_human_review() -> None:
    conflict = ConflictV1(
        conflict_id="conflict-1",
        project_id="project-1",
        category="SEMANTIC_AMBIGUITY",
        summary="The social meaning cannot be determined from the proposal alone.",
        affected_update_ids=["update-relationship-1"],
        evidence_refs=[EVIDENCE],
        blocking=False,
    )
    result = _review(_proposal(conflicts=[conflict]))

    assert result.decision == "NEEDS_HUMAN_REVIEW"
    assert {issue.category for issue in result.issues} == {"UNKNOWN_SEMANTIC_CONFLICT"}


def test_missing_timeline_anchor_is_rejected() -> None:
    result = _review(_proposal(state_event_id="event-missing"))

    assert result.decision == "REJECT"
    assert "TIMELINE_ANCHOR_MISSING" in {issue.category for issue in result.issues}


def test_deterministic_replay_returns_identical_result() -> None:
    proposal = _proposal()

    assert _review(proposal).model_dump(mode="json") == _review(proposal).model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    ("update_type", "expected_category"),
    [
        (ProfileUpdateProposalV1, "ENTITY_ID_DUPLICATE"),
        (RelationshipUpdateProposalV1, "RELATIONSHIP_ID_DUPLICATE"),
        (WorldRuleUpdateProposalV1, "WORLD_RULE_ID_DUPLICATE"),
    ],
)
def test_duplicate_resource_ids_return_reject(
    update_type: type[object], expected_category: str
) -> None:
    proposal = _proposal()
    source = next(
        update for update in proposal.commit_plan.updates if isinstance(update, update_type)
    )
    duplicate = source.model_copy(update={"update_id": f"duplicate-{source.update_id}"})
    plan = proposal.commit_plan.model_copy(
        update={"updates": [*proposal.commit_plan.updates, duplicate]}
    )
    duplicated = proposal.model_copy(update={"commit_plan": plan})

    result = _review(duplicated)

    assert result.decision == "REJECT"
    assert expected_category in {issue.category for issue in result.issues}


def test_canonical_entity_relationship_and_state_conflicts_are_rejected() -> None:
    canonical_entity = _profile("canonical-1", "Existing Person").model_copy(
        update={"aliases": ["Xia Ming"]}
    )
    canonical_other = _profile("profile-2", "Lin Yue")
    canonical_relationship = StoryRelationshipV1(
        relationship_id="canonical-relationship",
        project_id="project-1",
        source_profile_id="profile-1",
        target_profile_id="profile-2",
        relationship_type="FRIEND",
        attributes={"status": "hostile"},
        valid_from_order=0,
        evidence_refs=[EVIDENCE],
    )
    canonical_state = StoryEntityStateV1(
        state_id="canonical-state",
        project_id="project-1",
        profile_id="profile-1",
        state={"location": "home"},
        valid_from_order=0,
        evidence_refs=[EVIDENCE],
    )
    snapshot = StoryBibleCanonicalSnapshotV1(
        project_id="project-1",
        profiles=sorted(
            [canonical_entity, canonical_other], key=lambda item: item.profile_id
        ),
        states=[canonical_state],
        relationships=[canonical_relationship],
    )

    result = _review(_proposal(), snapshot=snapshot)

    assert result.decision == "REJECT"
    categories = {issue.category for issue in result.issues}
    assert "ENTITY_IDENTITY_CONFLICT" in categories
    assert "RELATIONSHIP_CONFLICT" in categories
    assert "CANONICAL_CONFLICT" in categories


def test_uncertain_relationship_overlap_requires_human_review() -> None:
    relationships = [
        StoryRelationshipV1(
            relationship_id="relationship-1",
            project_id="project-1",
            source_profile_id="profile-1",
            target_profile_id="profile-2",
            relationship_type="ALLY",
            attributes={"trust": "HIGH"},
            valid_from_order=0,
            evidence_refs=[EVIDENCE],
        ),
        StoryRelationshipV1(
            relationship_id="relationship-2",
            project_id="project-1",
            source_profile_id="profile-1",
            target_profile_id="profile-2",
            relationship_type="ALLY",
            attributes={"public_status": "SECRET"},
            valid_from_order=0,
            evidence_refs=[EVIDENCE],
        ),
    ]

    result = _review(_proposal(relationships=relationships))

    assert result.decision == "NEEDS_HUMAN_REVIEW"
    issue = next(issue for issue in result.issues if issue.category == "RELATIONSHIP_CONFLICT")
    assert issue.severity == "REVIEW_REQUIRED"
