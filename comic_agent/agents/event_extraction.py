"""Event extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EventProposalV1

EVENT_EXTRACTION_SYSTEM_PROMPT = """
You are a strict story event extraction agent.
You may only use the provided source_chunks.
Extract one main event as EventProposalV1 JSON.
Do not invent events, participants, locations, dialogue, claims, or knowledge states.
Evidence quote_text must be copied exactly from one source chunk.
Use actor_resolution_status=KNOWN only when participant_ids are evidence-supported.
Use actor_resolution_status=UNKNOWN or UNRESOLVED when the actor is not confirmed.
Do not output ClaimProposalV1, KnowledgeStateProposalV1, or canonical story data.
Return JSON only.
""".strip()


class EventExtractionAgent:
    """Minimal real event extraction agent that returns EventProposalV1 only."""

    spec = AgentSpec(
        agent_id="event-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="EventProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> EventProposalV1:
        """Extract one event proposal from bounded source context."""

        return self._provider.structured_generate(
            {
                "system_prompt": EVENT_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Extract exactly one major EventProposalV1 from the provided "
                    "source_chunks. Preserve source fidelity and include EvidenceRef."
                ),
                "input_context": input_context,
            },
            EventProposalV1,
        )
