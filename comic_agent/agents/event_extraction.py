"""Event extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EventProposalBatchV1

EVENT_EXTRACTION_SYSTEM_PROMPT = """
You are EventExtractionAgent prompt v0.1, a strict story event extraction agent.
You may only use input_context.source_chunks and input_context.source_chunk_ids.
Return exactly one EventProposalBatchV1 JSON object.
Extract all salient story events visible in the selected SourceChunk records.
Return 1 or more EventProposalV1 records inside events.
The number of events must be based on actual story events, not chunk count.
If one chunk contains multiple events, output multiple events.
If multiple chunks narrate one continuous event, output one event.
Do not invent events to match chunk count.
Do not duplicate the same event.
Sort events by source order.
Select one concrete, evidence-backed event quickly.
Do not reason step by step.
Do not list candidate events.
Do not explain your choice.
Each event summary must faithfully describe one source-text event.
summary must only state facts directly supported by that event's evidence quote.
Every actor, action, object, and outcome mentioned in each summary must be visible
or directly inferable from that event's quote.
Every actor, action, object, and outcome must be directly inferable from the quote.
Every event summary must be directly supported by its own evidence quote.
If the quote only supports part of a larger event, narrow the summary to that
supported part.
If evidence only supports a narrower event, narrow that event summary.
Do not include extra context from surrounding text in summary unless it is also
covered by the quote.
Keep summary concise.
Keep summary concise, preferably under 30 Chinese characters.
If the chunk is mostly background or setup, still choose the most concrete
event-like change or action that is directly evidenced.
Do not merge multiple events into one proposal.
Do not merge adjacent events into one proposal.
Do not combine action + later explanation/announcement/reaction into one event
unless the same quote directly states both.
Do not invent characters, locations, dialogue, relationships, motives, thoughts,
causality, settings, or facts.
Each event_type should name a single event, not a merged category.
Avoid joined labels like suppression_and_announcement unless the evidence quote
directly supports both parts.
Prefer concise event_type labels such as poison_suppressed, announcement_made,
character_arrives, attack_started, decision_made.
participant_ids may only use ids already present in the provided context and supported by evidence.
When the actor is uncertain, use actor_resolution_status=UNKNOWN or UNRESOLVED
instead of forcing a character id.
evidence_refs must contain at least one EvidenceRefV1.
Each evidence chunk_id must come from input_context.source_chunk_ids.
Each evidence quote_text must be copied exactly from the matching SourceChunkV1.text.
Every event must have evidence_refs with quote_text copied verbatim from source_chunks.
Use the shortest exact quote that supports the event.
Use the shortest exact quote that supports the full summary.
Use the shortest exact source quote for evidence.
Prefer one quote containing the actor + action + outcome.
If no short quote supports the full broad event, choose a narrower event instead.
quote_text must be copied verbatim from the selected source chunk.
Do not paraphrase, summarize, translate, merge, or rewrite quote_text.
If quote_start and quote_end are provided, they must exactly match quote_text in that chunk.
If quote_start/quote_end are uncertain, omit them or set them null.
quote_text must exact-match the chunk text.
Prefer a 6-40 Chinese character quote that contains the core action/result.
If evidence only partially supports the summary, narrow summary; do not keep
broad summary with high confidence.
High confidence requires evidence quote to fully support summary.
Choose reality_layer conservatively; use UNKNOWN when the layer cannot be confirmed.
Do not output ClaimProposalV1, EntityProposalV1, KnowledgeStateProposalV1, or canonical story data.
Return final EventProposalBatchV1 JSON only.
Return final JSON directly. JSON only. Do not include reasoning.
Do not return markdown or explanations.
""".strip()


class EventExtractionAgent:
    """Minimal real event extraction agent that returns EventProposalBatchV1 only."""

    spec = AgentSpec(
        agent_id="event-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="EventProposalBatchV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> EventProposalBatchV1:
        """Extract one event proposal batch from bounded source context."""

        return self._provider.structured_generate(
            {
                "system_prompt": EVENT_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Use input_context project_id, source_chunk_ids, and "
                    "source_chunks. Return one EventProposalBatchV1."
                ),
                "input_context": input_context,
            },
            EventProposalBatchV1,
        )
