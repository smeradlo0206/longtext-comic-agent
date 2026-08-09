"""Entity extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import EntityProposalBatchV1

ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are EntityExtractionAgent prompt v0.1, a strict story entity extraction agent.
You may only use the provided input_context.source_chunks.
You may only cite chunk ids from input_context.source_chunk_ids.
Extract one EntityProposalBatchV1 with schema_version="1.1" containing all
significant distinct EntityProposalV1 items from the current source_chunks.
Return EntityProposalBatchV1 JSON only.
The batch must contain a non-empty entities array.
Do not return a single EntityProposalV1.
Do not return another mode's batch.
When input_context.output_recovery is present, reissue the complete final batch JSON.
Do not mention the recovery directive.
The number of entities must be based on real entities, not chunk count.
One chunk can contain multiple entities, and three chunks can still contain one
entity if only one distinct significant entity is present.
If the same entity appears across chunks, output it once with the best compact evidence.
Do not duplicate aliases or proposal ids.
Choose important, specific, reusable entities from the current source_chunks.
Prefer entities that affect later story understanding.
Do not choose generic common nouns.
Do not treat ordinary actions, events, or claims as entities.
Do not treat ordinary actions, event results, or character judgments as entities.
Use exactly these entity_type labels when supported by source text:
CHARACTER: human beings or entities with a clear personhood or social identity.
CREATURE: non-human animals, demon beasts, magical beasts, spirit beasts, or monsters.
Named non-human creatures such as "Flame-Armored Rhinoceros" are CREATURE, not CHARACTER.
For CREATURE only, creature_subtype may be ANIMAL, MONSTER, SPIRIT_BEAST, or OTHER
when the source directly supports it; otherwise set creature_subtype=null. Do not invent a subtype.
LOCATION: places, regions, sect sites, or spaces.
ORGANIZATION: sects, dynasties, factions, families, or teams.
OBJECT: artifacts, weapons, tokens, pills, and important reusable objects, including
important unnamed objects. Do not extract ordinary generic nouns.
ABILITY: cultivation methods, source arts, moves, abilities, techniques, or skills.
CONCEPT: realms, rules, institutions, power systems, and world-setting concepts.
Do not classify every fictional proper noun as CONCEPT.
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
Each EntityProposalV1 must have independent evidence_refs with at least one EvidenceRefV1.
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
Before responding, verify the outer object is EntityProposalBatchV1 and every item
belongs in entities.
Return final EntityProposalBatchV1 JSON only.
Return final JSON only. JSON only.
Do not return markdown or explanations.
""".strip()


class EntityExtractionAgent:
    """Minimal entity extraction agent that returns EntityProposalBatchV1 only."""

    spec = AgentSpec(
        agent_id="entity-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="EntityProposalBatchV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> EntityProposalBatchV1:
        """Extract one entity proposal batch from bounded source context."""

        return self._provider.structured_generate(
            {
                "system_prompt": ENTITY_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Input includes project_id, source_chunk_ids, and source_chunks. "
                    "Return one EntityProposalBatchV1 with all distinct significant "
                    "source-grounded entities. Handle uncertainty conservatively and "
                    "include EvidenceRef for every entity."
                ),
                "input_context": input_context,
            },
            EntityProposalBatchV1,
        )
