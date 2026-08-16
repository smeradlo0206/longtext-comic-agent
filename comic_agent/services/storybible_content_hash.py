"""Deterministic content hashing for StoryBible commit plans."""

import hashlib
import json

from comic_agent.schemas.storybible import CommitPlanV1


def compute_content_hash(plan: CommitPlanV1) -> str:
    """Return a stable SHA-256 hash of a commit plan's canonical content.

    The hash covers every field except plan-identity fields (``content_hash``,
    ``commit_plan_id``, and ``source_proposal_id``). Two plans that propose the
    same canonical updates therefore always share the same hash while any content
    difference produces a different one. The model must not choose this value: it
    is always recomputed server-side before a candidate plan is persisted, which
    keeps repeated curation idempotent and prevents provider-chosen keys from
    colliding.
    """

    payload = plan.model_dump(
        mode="json",
        exclude={"content_hash", "commit_plan_id", "source_proposal_id"},
    )
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def with_computed_content_hash(plan: CommitPlanV1) -> CommitPlanV1:
    """Return the plan carrying the computed content hash, or the plan unchanged."""

    computed = compute_content_hash(plan)
    if plan.content_hash == computed:
        return plan
    return plan.model_copy(update={"content_hash": computed})
