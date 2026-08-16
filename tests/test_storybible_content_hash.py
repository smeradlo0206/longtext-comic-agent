"""Deterministic content hashing for StoryBible commit plans."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StoryEntityProfileV1,
)
from comic_agent.services.storybible_content_hash import (
    compute_content_hash,
    with_computed_content_hash,
)


def plan(*, name: str = "Lin Xia", content_hash: str | None = "provider-hash") -> CommitPlanV1:
    evidence = [EvidenceRefV1(chunk_id="chunk-a")]
    return CommitPlanV1(
        commit_plan_id="plan-a",
        project_id="project-a",
        source_proposal_id="proposal-a",
        content_hash=content_hash,
        updates=[
            ProfileUpdateProposalV1(
                update_id="update-a",
                project_id="project-a",
                profile=StoryEntityProfileV1(
                    profile_id="profile-a",
                    project_id="project-a",
                    entity_kind="PERSON",
                    canonical_name=name,
                    evidence_refs=evidence,
                ),
                evidence_refs=evidence,
            )
        ],
        evidence_refs=evidence,
    )


def test_content_hash_is_deterministic_for_identical_content() -> None:
    assert compute_content_hash(plan()) == compute_content_hash(plan())


def test_content_hash_ignores_the_provider_supplied_hash_field() -> None:
    same_content_different_hashes = plan(content_hash="hash-a")
    same_content_no_hash = plan(content_hash=None)
    assert compute_content_hash(same_content_different_hashes) == compute_content_hash(
        same_content_no_hash
    )


def test_content_hash_changes_when_plan_content_changes() -> None:
    assert compute_content_hash(plan(name="Lin Xia")) != compute_content_hash(plan(name="Lin Ya"))


def test_content_hash_is_a_sha256_hexdigest() -> None:
    digest = compute_content_hash(plan())
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_with_computed_content_hash_overwrites_a_provider_hash() -> None:
    original = plan(content_hash="provider-hash")
    hashed = with_computed_content_hash(original)
    assert hashed.content_hash == compute_content_hash(original)
    assert hashed.content_hash != "provider-hash"


def test_with_computed_content_hash_keeps_an_already_computed_hash() -> None:
    original = plan(content_hash=None)
    computed = with_computed_content_hash(original)
    assert with_computed_content_hash(computed) is computed


def test_commit_plan_accepts_an_omitted_content_hash() -> None:
    evidence = [EvidenceRefV1(chunk_id="chunk-a")]
    candidate = CommitPlanV1(
        commit_plan_id="plan-a",
        project_id="project-a",
        source_proposal_id="proposal-a",
        updates=[
            ProfileUpdateProposalV1(
                update_id="update-a",
                project_id="project-a",
                profile=StoryEntityProfileV1(
                    profile_id="profile-a",
                    project_id="project-a",
                    entity_kind="PERSON",
                    canonical_name="Lin Xia",
                    evidence_refs=evidence,
                ),
                evidence_refs=evidence,
            )
        ],
        evidence_refs=evidence,
    )
    assert candidate.content_hash is None
