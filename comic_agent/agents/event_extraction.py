"""Event extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EventProposalV1

EVENT_EXTRACTION_SYSTEM_PROMPT = """
You are EventExtractionAgent prompt v0.1, a strict story event extraction agent.
You may only use input_context.source_chunks and input_context.source_chunk_ids.
Return exactly one event proposal as EventProposalV1 JSON.
Choose the single most salient event across selected chunks.
Select one concrete, evidence-backed event quickly.
Do not reason step by step.
Do not list candidate events.
Do not explain your choice.
The summary must faithfully describe one source-text event.
Keep summary concise.
Keep summary concise, preferably under 30 Chinese characters.
If the chunk is mostly background or setup, still choose the most concrete
event-like change or action that is directly evidenced.
Do not merge multiple events into one proposal.
Do not invent characters, locations, dialogue, relationships, motives, thoughts,
causality, settings, or facts.
participant_ids may only use ids already present in the provided context and supported by evidence.
When the actor is uncertain, use actor_resolution_status=UNKNOWN or UNRESOLVED
instead of forcing a character id.
evidence_refs must contain at least one EvidenceRefV1.
Each evidence chunk_id must come from input_context.source_chunk_ids.
Each evidence quote_text must be copied exactly from the matching SourceChunkV1.text.
Use the shortest exact quote that supports the event.
Use the shortest exact source quote for evidence.
quote_text must be copied verbatim from the selected source chunk.
Do not paraphrase, summarize, translate, merge, or rewrite quote_text.
If quote_start and quote_end are provided, they must exactly match quote_text in that chunk.
If quote_start/quote_end are uncertain, omit them or set them null.
quote_text must exact-match the chunk text.
Prefer a 6-40 Chinese character quote that contains the core action/result.
Choose reality_layer conservatively; use UNKNOWN when the layer cannot be confirmed.
Do not output ClaimProposalV1, EntityProposalV1, KnowledgeStateProposalV1, or canonical story data.
Return final EventProposalV1 JSON only.
Return final JSON directly. JSON only. Do not include reasoning.
Do not return markdown or explanations.
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
                    "Use input_context project_id, source_chunk_ids, and "
                    "source_chunks. Return one EventProposalV1."
                ),
                "input_context": input_context,
            },
            EventProposalV1,
        )
