"""Deterministic identity for StoryBible review inputs."""

import json
from hashlib import sha256

from comic_agent.schemas.storybible import StoryBibleCuratorProposalV1


def storybible_proposal_hash(proposal: StoryBibleCuratorProposalV1) -> str:
    """Hash the complete normalized proposal using stable JSON serialization."""

    canonical = json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
