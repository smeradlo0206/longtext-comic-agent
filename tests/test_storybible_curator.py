import json
from typing import Any, TypeVar

from pydantic import BaseModel

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.narrative import TemporalRelation, TemporalRelationProposalV1
from comic_agent.schemas.storybible import (
    StateUpdateProposalV1,
    StoryBibleContextV1,
    StoryBibleCuratorProposalV1,
)
from comic_agent.services.storybible_content_hash import compute_content_hash

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _candidate_payload(
    *,
    status: str = "CANONICAL",
    confidence: float = 0.9,
    content_hash: str | None = "hash-1",
) -> dict[str, Any]:
    evidence = {"chunk_id": "chunk-1"}
    profile = {
        "profile_id": "profile-1",
        "project_id": "project-1",
        "entity_kind": "PERSON",
        "canonical_name": "Lin Xia",
        "evidence_refs": [evidence],
    }
    update = {
        "update_id": "update-1",
        "project_id": "project-1",
        "profile": profile,
        "evidence_refs": [evidence],
    }
    commit_plan = {
        "commit_plan_id": "plan-1",
        "project_id": "project-1",
        "source_proposal_id": "curator-1",
        "updates": [update],
        "evidence_refs": [evidence],
    }
    if content_hash is not None:
        commit_plan["content_hash"] = content_hash
    return {
        "proposal_id": "curator-1",
        "project_id": "project-1",
        "status": status,
        "commit_plan": commit_plan,
        "evidence_refs": [evidence],
        "confidence": confidence,
    }


class RecordingProvider:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.request: dict[str, object] | None = None
        self.output_model: type[BaseModel] | None = None

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.request = request
        self.output_model = output_model
        return output_model.model_validate(self.response)


def test_curator_returns_only_a_schema_valid_candidate() -> None:
    provider = RecordingProvider(_candidate_payload())
    curator = StoryBibleCurator(provider)

    proposal = curator.run(
        StoryBibleContextV1(project_id="project-1", source_chunk_ids=["chunk-1"])
    )

    assert isinstance(proposal, StoryBibleCuratorProposalV1)
    assert proposal.commit_plan.project_id == "project-1"
    assert proposal.status == RecordStatus.CANDIDATE
    assert provider.output_model is StoryBibleCuratorProposalV1


def test_curator_sends_only_bounded_context_to_provider() -> None:
    provider = RecordingProvider(_candidate_payload(status="CANDIDATE"))
    curator = StoryBibleCurator(provider)
    context = StoryBibleContextV1(project_id="project-1", source_chunk_ids=["chunk-1"])

    curator.run(context)

    assert provider.request is not None
    messages = provider.request["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    assert json.loads(str(user_message["content"])) == context.model_dump(mode="json")
    assert "database" not in str(provider.request).casefold()


def test_curator_spec_forbids_canonical_writes() -> None:
    assert StoryBibleCurator.spec.can_write_canonical_data is False
    assert StoryBibleCurator.spec.reads == ["StoryBibleContextV1"]
    assert StoryBibleCurator.spec.output_schema == "StoryBibleCuratorProposalV1"
    assert StoryBibleCurator.spec.max_context_chunks == 3


def test_curator_replaces_provider_hash_with_a_deterministic_content_hash() -> None:
    provider = RecordingProvider(_candidate_payload(content_hash="provider-hash"))
    curator = StoryBibleCurator(provider)
    context = StoryBibleContextV1(project_id="project-1", source_chunk_ids=["chunk-1"])

    proposal = curator.run(context)

    assert proposal.commit_plan.content_hash == compute_content_hash(proposal.commit_plan)
    assert proposal.commit_plan.content_hash != "provider-hash"


def test_curator_computes_the_hash_when_the_provider_omits_it() -> None:
    provider = RecordingProvider(_candidate_payload(content_hash=None))
    curator = StoryBibleCurator(provider)

    proposal = curator.run(StoryBibleContextV1(project_id="project-1"))

    assert proposal.commit_plan.content_hash == compute_content_hash(proposal.commit_plan)


def test_identical_drafts_receive_identical_hashes() -> None:
    first = StoryBibleCurator(RecordingProvider(_candidate_payload())).run(
        StoryBibleContextV1(project_id="project-1")
    )
    second = StoryBibleCurator(RecordingProvider(_candidate_payload())).run(
        StoryBibleContextV1(project_id="project-1")
    )
    assert first.commit_plan.content_hash == second.commit_plan.content_hash


def test_curator_preserves_event_anchors_and_leaves_orders_to_the_timeline_agent() -> None:
    """The state library anchors states to events but never derives event order."""

    evidence = {"chunk_id": "chunk-1"}
    payload = _candidate_payload()
    state = {
        "state_id": "project-1:state-a",
        "project_id": "project-1",
        "profile_id": "project-1:profile-a",
        "state": {"location": "market"},
        "valid_from_event_id": "project-1:event-2",
        "valid_until_event_id": "project-1:event-4",
        "evidence_refs": [evidence],
    }
    payload["commit_plan"]["updates"].append(
        {
            "update_id": "project-1:update-state",
            "project_id": "project-1",
            "state": state,
            "evidence_refs": [evidence],
        }
    )
    provider = RecordingProvider(payload)
    curator = StoryBibleCurator(provider)
    context = StoryBibleContextV1(
        project_id="project-1",
        temporal_relation_proposals=[
            TemporalRelationProposalV1(
                proposal_id="rel-1",
                source_event_id="project-1:event-1",
                target_event_id="project-1:event-2",
                relation=TemporalRelation.BEFORE,
                evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
                confidence=0.9,
            ),
        ],
    )

    proposal = curator.run(context)

    state_updates = [
        update
        for update in proposal.commit_plan.updates
        if isinstance(update, StateUpdateProposalV1)
    ]
    assert len(state_updates) == 1
    assert state_updates[0].state.valid_from_event_id == "project-1:event-2"
    assert state_updates[0].state.valid_until_event_id == "project-1:event-4"
    assert state_updates[0].state.valid_from_order is None
    assert state_updates[0].state.valid_until_order is None


def test_low_confidence_draft_gains_a_blocking_review_conflict() -> None:
    provider = RecordingProvider(_candidate_payload(confidence=0.4))
    curator = StoryBibleCurator(provider)

    proposal = curator.run(StoryBibleContextV1(project_id="project-1"))

    assert len(proposal.conflicts) == 1
    conflict = proposal.conflicts[0]
    assert conflict.category == "LOW_CONFIDENCE"
    assert conflict.blocking is True
    assert conflict.affected_update_ids == ["update-1"]
    assert proposal.status == RecordStatus.CANDIDATE


def test_sufficient_confidence_draft_gains_no_review_conflict() -> None:
    provider = RecordingProvider(_candidate_payload(confidence=0.95))
    curator = StoryBibleCurator(provider)

    proposal = curator.run(StoryBibleContextV1(project_id="project-1"))

    assert proposal.conflicts == []


def test_output_schema_supports_all_update_kinds_and_conflicts() -> None:
    curator = StoryBibleCurator(RecordingProvider(_candidate_payload()))
    schema = curator._output_schema()
    variants = schema["properties"]["commit_plan"]["properties"]["updates"]["items"]["oneOf"]
    variant_keys = {",".join(sorted(variant["properties"])) for variant in variants}
    assert any("profile" in keys for keys in variant_keys)
    assert any("relationship" in keys for keys in variant_keys)
    assert any("state" in keys for keys in variant_keys)
    assert any("world_rule" in keys for keys in variant_keys)
    assert "conflict" in schema["definitions"]


def test_system_prompt_consolidates_reviewed_proposals_and_anchors_states() -> None:
    provider = RecordingProvider(_candidate_payload())
    curator = StoryBibleCurator(provider)
    curator.run(StoryBibleContextV1(project_id="project-1"))
    assert provider.request is not None
    system_content = str(provider.request["messages"][0]["content"])
    assert "CONSOLIDATE" in system_content
    assert "state_change_proposals" in system_content
    assert "temporal_relation_proposals" in system_content
    assert "CHARACTER -> PERSON" in system_content
    assert "EVENT ANCHORING, NOT ORDERING" in system_content
    assert "timeline agent" in system_content

