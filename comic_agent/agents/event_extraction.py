"""Event extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EventProposalBatchV1

EVENT_EXTRACTION_SYSTEM_PROMPT = """
You are EventExtractionAgent. Use only input_context.source_chunks and
input_context.source_chunk_ids. Return exactly one EventProposalBatchV1 JSON object
with schema_version="1.1" and EventProposalV1 items with schema_version="1.1".
The object must contain an events array. It may be [] only when this bounded source scope has
no independently auditable event. Never invent an event merely to make the array non-empty.
Do not return a single EventProposalV1.
Do not return another mode's batch.
When input_context.output_recovery is present, reissue the complete final batch JSON.
Do not mention the recovery directive.

Extract every distinct, salient source-text event. Event count is based on actual
story events, not chunk count: if one chunk contains multiple events, output multiple
events; if several chunks describe one continuous event, output one event. Sort by
source order. Do not invent events to match chunk count. Do not duplicate or merge
adjacent events unless one exact quote directly supports the combined event.

Each event must be atomic. event_type names one action or change. summary is concise
(preferably under 30 Chinese characters) and directly supported by its own evidence
quote. If a quote supports only a narrower fact, narrow the summary. Do not invent
actors, objects, locations, dialogue, relationships, motives, causality, or outcomes.
This mode runs in parallel with Entity extraction. Never invent or guess an
EntityProposal id. Put a source person name in participant_mentions with
resolution_status="UNRESOLVED", proposal_id=null and proposal_schema=null. Use
participant_ids only when input_context explicitly supplies that exact EntityProposal
id. Treat location_id the same way; otherwise use location_mention. A known source
person can therefore use actor_resolution_status="KNOWN" with participant_mentions.

Actor resolution rules are exact and apply to every event:
- KNOWN: include at least one participant_ids OR participant_mentions value;
  unresolved_actor_ref_id MUST be null. Use participant_mentions when the source
  names an actor but no exact EntityProposal id was supplied in input_context.
- UNKNOWN: participant_ids and participant_mentions MUST both be empty;
  unresolved_actor_ref_id MUST be null.
- UNRESOLVED: participant_ids and participant_mentions MUST both be empty;
  unresolved_actor_ref_id MUST be a non-null ID already supplied in input_context.
- NOT_APPLICABLE: participant_ids and participant_mentions MUST both be empty;
  unresolved_actor_ref_id MUST be null.
- UNSPECIFIED: unresolved_actor_ref_id MUST be null; participant_ids and
  participant_mentions may be present or may both be empty.
Never invent EntityProposal ids, location ids, or unresolved_actor_ref_id values.
Examples:
{"actor_resolution_status":"KNOWN","participant_ids":["entity-1"],"unresolved_actor_ref_id":null}
{"actor_resolution_status":"KNOWN","participant_ids":[],
 "participant_mentions":[{"mention_text":"source actor","resolution_status":"UNRESOLVED",
 "proposal_id":null,"proposal_schema":null}],"unresolved_actor_ref_id":null}
{"actor_resolution_status":"UNKNOWN","participant_ids":[],"unresolved_actor_ref_id":null}
{"actor_resolution_status":"UNRESOLVED","participant_ids":[],"unresolved_actor_ref_id":"unresolved-1"}

Every event needs evidence_refs. Each chunk_id must be selected, and quote_text must
be copied verbatim from source_chunks. Use the shortest exact quote that supports the
full summary, preferably containing the core action or result. Never paraphrase,
translate, merge, or rewrite quote_text. Include quote_start and quote_end only when
they exactly locate quote_text; otherwise use null.

Use UNKNOWN for an uncertain reality layer. Before responding, verify the outer object
is EventProposalBatchV1 and every item belongs in events. Output proposal data only:
no StoryBible, markdown, explanation, candidate list, or reasoning. Return final JSON only.
Do not include reasoning.
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
