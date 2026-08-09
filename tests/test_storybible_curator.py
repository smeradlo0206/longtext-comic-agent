import json
from typing import Any, TypeVar

from pydantic import BaseModel

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.storybible import StoryBibleContextV1, StoryBibleCuratorProposalV1

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _candidate_payload(*, status: str = "CANONICAL") -> dict[str, Any]:
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
    return {
        "proposal_id": "curator-1",
        "project_id": "project-1",
        "status": status,
        "commit_plan": {
            "commit_plan_id": "plan-1",
            "project_id": "project-1",
            "source_proposal_id": "curator-1",
            "content_hash": "hash-1",
            "updates": [update],
            "evidence_refs": [evidence],
        },
        "evidence_refs": [evidence],
        "confidence": 0.9,
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
