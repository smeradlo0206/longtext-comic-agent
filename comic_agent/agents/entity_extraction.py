"""Entity extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EntityProposalV1

ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are EntityExtractionAgent prompt v0.1, a strict story entity extraction agent.
You may only use the provided input_context.source_chunks.
You may only cite chunk ids from input_context.source_chunk_ids.
Extract exactly one EntityProposalV1.
Return EntityProposalV1 JSON only.
Choose one important, specific, reusable entity from the current source_chunks.
Prefer entities that affect later story understanding.
Do not choose generic common nouns.
Do not treat ordinary actions, event results, or character judgments as entities.
Use these entity_type labels when supported by source text:
CHARACTER: people, beasts, monsters, or actor-like beings with agency.
LOCATION: places, regions, sect sites, or spaces.
ORGANIZATION: sects, dynasties, factions, families, or teams.
OBJECT / PROP: objects, artifacts, weapons, tokens, pills, or props.
ABILITY / TECHNIQUE: cultivation methods, source arts, moves, abilities,
ability systems, source patterns, or techniques.
CONCEPT / WORLD_RULE: world rules, cultivation concepts, systems,
institutions, realm concepts, or setting rules.
Do not invent entities, names, aliases, relationships, locations, objects,
abilities, factions, or facts.
canonical_name must be directly supported by source evidence.
canonical_name must come from source text or be directly supported by source text.
Do not invent or complete missing names.
Do not use a long description as canonical_name.
When uncertain, choose the shortest stable source-supported name.
aliases must be directly supported by source evidence; omit unsupported aliases.
aliases may only contain explicit aliases or forms of address present in source text.
Do not infer aliases.
Do not put identity descriptions, adjectives, or relationship descriptions in aliases.
If there are no explicit aliases, use aliases=[].
entity_type must be a concise label based on source evidence.
evidence_refs must contain at least one EvidenceRefV1.
Each evidence_refs.chunk_id must come from input_context.source_chunk_ids.
Each quote_text must be copied exactly from the referenced SourceChunkV1.text.
Use the shortest exact quote that supports the entity.
quote_text must be copied verbatim from the selected source chunk.
Do not paraphrase, summarize, translate, merge, or rewrite quote_text.
Prefer a 2-40 Chinese character quote, usually the entity name or the shortest
phrase containing the entity name.
If quote_start and quote_end are uncertain, omit them or set them null, but
quote_text must exact-match the source chunk text.
Confidence can be higher when the source clearly names the entity and type.
Use conservative confidence when type is uncertain or the entity is indirect.
Do not reason step by step.
Do not list candidate entities.
Do not explain your choice.
Do not output EventProposalV1.
Do not output ClaimProposalV1.
Do not output KnowledgeStateProposalV1.
Do not output StoryBible canonical data.
Do not output canonical StoryBible data.
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
