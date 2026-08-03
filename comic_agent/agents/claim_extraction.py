"""Claim extraction agent backed by an LLM provider."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import ClaimProposalV1

CLAIM_EXTRACTION_SYSTEM_PROMPT = """
You are ClaimExtractionAgent prompt v0.1, a strict story claim extraction agent.
You may only use input_context.source_chunks and input_context.source_chunk_ids.
Return exactly one claim proposal as ClaimProposalV1 JSON.
Choose the single most important claim across selected SourceChunk records.
A claim may be a character statement, narrator judgment, memory, guess, denial,
accusation, prediction, or interpretation.
Do not output EventProposalV1; do not extract the event itself.
Do not output EntityProposalV1; do not extract the entity itself.
Do not write canonical StoryBible data.
Do not invent claims, speakers, source ids, target events, facts, or verification.
evidence_refs must contain at least one EvidenceRefV1.
Each evidence chunk_id must come from input_context.source_chunk_ids.
Each evidence quote_text must be copied exactly from the matching SourceChunkV1.text.
Use the shortest exact quote that supports the claim.
If source_id is uncertain, use a conservative source_type such as UNKNOWN,
NARRATOR, CHARACTER, MESSAGE, or another value allowed by ClaimProposalV1.
verification_status should be conservative; default to UNVERIFIED unless the
provided text explicitly supports, confirms, contradicts, or partially supports it.
Choose reality_layer from source context; use UNKNOWN when the layer cannot be confirmed.
Return final JSON directly. JSON only. Do not include reasoning.
Do not return markdown or explanations.
""".strip()


class ClaimExtractionAgent:
    """Minimal claim extraction agent that returns ClaimProposalV1 only."""

    spec = AgentSpec(
        agent_id="claim-extraction-agent",
        version="0.1",
        reads=["SourceChunkV1"],
        output_schema="ClaimProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> ClaimProposalV1:
        """Extract one claim proposal from bounded source context."""

        return self._provider.structured_generate(
            {
                "system_prompt": CLAIM_EXTRACTION_SYSTEM_PROMPT,
                "user_prompt": (
                    "Use input_context project_id, source_chunk_ids, and source_chunks. "
                    "Return one ClaimProposalV1."
                ),
                "input_context": input_context,
            },
            ClaimProposalV1,
        )
