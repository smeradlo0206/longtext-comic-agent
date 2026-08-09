"""Proposal-only StoryBible curator backed by a structured LLM provider."""

import json

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.storybible import StoryBibleContextV1, StoryBibleCuratorProposalV1


class StoryBibleCurator:
    """Turn bounded StoryBible context into a schema-validated candidate proposal."""

    spec = AgentSpec(
        agent_id="storybible-curator",
        version="1.0",
        reads=["StoryBibleContextV1"],
        output_schema="StoryBibleCuratorProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, context: StoryBibleContextV1) -> StoryBibleCuratorProposalV1:
        """Generate a candidate without accessing or writing canonical storage."""

        response = self._provider.structured_generate(
            self._request(context),
            StoryBibleCuratorProposalV1,
        )
        return response.model_copy(update={"status": RecordStatus.CANDIDATE})

    def _request(self, context: StoryBibleContextV1) -> dict[str, object]:
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Create one evidence-backed StoryBibleCuratorProposalV1 candidate. "
                        "Use only the supplied bounded context. Do not invent evidence and do "
                        "not claim to write canonical data. Return a JSON object only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        context.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
        }
