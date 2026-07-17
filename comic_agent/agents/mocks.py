"""Mock agent implementations for tests and examples."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.schemas.narrative import EventProposalV1


class MockEventAgent:
    """Predictable event extraction agent backed by MockLLMProvider."""

    spec = AgentSpec(
        agent_id="mock-event-agent",
        version="1.0",
        reads=["SourceChunkV1"],
        output_schema="EventProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: MockLLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> EventProposalV1:
        """Return a deterministic event proposal."""

        return self._provider.structured_generate(input_context, EventProposalV1)
