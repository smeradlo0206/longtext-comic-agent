"""Entity extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EntityProposalV1

ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are EntityExtractionAgent prompt v0.1, a strict story entity extraction agent.
You may only use the provided input_context.source_chunks.
You may only cite chunk ids from input_context.source_chunk_ids.
Extract exactly one EntityProposalV1.
The entity may be a CHARACTER, LOCATION, PROP, ORGANIZATION, FACTION, SPECIES,
ABILITY, ITEM, or other source-grounded entity type.
Do not invent entities, names, aliases, relationships, locations, objects,
abilities, factions, or facts.
canonical_name must be directly supported by source evidence.
aliases must be directly supported by source evidence; omit unsupported aliases.
entity_type must be a concise label based on source evidence.
evidence_refs must contain at least one EvidenceRefV1.
Each evidence_refs.chunk_id must come from input_context.source_chunk_ids.
Each quote_text must be copied exactly from the referenced SourceChunkV1.text.
Use the shortest exact quote that supports the entity.
Do not output EventProposalV1, ClaimProposalV1, KnowledgeStateProposalV1,
or canonical StoryBible data.
Return final JSON only. JSON only.
Do not return markdown or explanations.
""".strip()


class EntityExtractionAgent:
    """Minimal entity extraction agent that returns EntityProposalV1 only."""

    spec = AgentSpec(
        agent_id="entity-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="EntityProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> EntityProposalV1:
        """Extract one entity proposal from bounded source context."""

        return self._provider.structured_generate(
            {
                "system_prompt": ENTITY_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Input includes project_id, source_chunk_ids, and source_chunks. "
                    "Extract exactly one source-grounded entity, handle uncertainty "
                    "conservatively, and include EvidenceRef."
                ),
                "input_context": input_context,
            },
            EntityProposalV1,
        )
