"""Bounded campus-content profile extraction from supplied factual Claim proposals."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.narrative import (
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    ClaimType,
)
from comic_agent.schemas.source import SourceChunkV1

CAMPUS_CONTENT_PROFILE_SYSTEM_PROMPT = """
You are CampusContentProfileAgent. Return exactly one CampusContentProfileProposalV1
candidate, never a canonical StoryBible record, ComicBeatProposalV1, panel, prompt, or
timeline request. Use only input_context.source_chunks, source_chunk_ids, factual
input_context.claim_proposals, and their explicitly supplied same-project mapping.

Choose content_type only from campus_news, event_promotion, recruitment, public_service;
choose audience only from student, parent, teacher, public; choose tone only from formal,
lively, youthful. page_budget must be an integer from 1 through 24.

must_preserve_fact_ids must contain only supplied factual ClaimProposalV1.claim_id values.
They may preserve dates, places, organizers, activity names, or registration details only
when the selected claim has exact EvidenceRef support. Never turn promotional language such
as broad praise or lively response into a fact. Never invent attendance counts, awards,
relationships, event steps, or facts. Copy Profile evidence only from the selected factual
claim evidence and selected SourceChunk text.

Do not generate ComicBeatProposalV1. Do not call Timeline, StoryBible, CommitService, image
tools, providers other than this structured response, or any database. The result remains a
CANDIDATE and awaits Review Gate 2. Return JSON only.
""".strip()


class CampusContentProfileAgent:
    """Generate one candidate Profile from bounded, caller-supplied factual Claims."""

    spec = AgentSpec(
        agent_id="campus-content-profile-agent",
        version="1.0",
        reads=["SourceChunkV1", "ClaimProposalV1"],
        output_schema="CampusContentProfileProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(self, input_context: dict[str, object]) -> CampusContentProfileProposalV1:
        """Request a Profile then verify every fact and Evidence remains in scope."""

        source_text_by_chunk_id = _source_text_by_chunk_id(input_context)
        project_id = _require_project_id(input_context)
        claims = _factual_claims(input_context, project_id)
        profile = self._provider.structured_generate(
            {
                "system_prompt": CAMPUS_CONTENT_PROFILE_SYSTEM_PROMPT,
                "user_prompt": (
                    "Use only the supplied factual ClaimProposalV1 candidates and selected "
                    "SourceChunkV1 records. Return one CampusContentProfileProposalV1 JSON."
                ),
                "input_context": input_context,
            },
            CampusContentProfileProposalV1,
        )
        if profile.project_id != project_id:
            raise ValueError(
                "CampusContentProfileAgent profile project_id must match input_context"
            )
        selected_claims: list[ClaimProposalV1] = []
        for fact_id in profile.must_preserve_fact_ids:
            claim = claims.get(fact_id)
            if claim is None:
                raise ValueError(
                    "CampusContentProfileAgent fact ids must resolve to supplied factual Claims"
                )
            selected_claims.append(claim)
        allowed_evidence = {
            (item.chunk_id, item.quote_start, item.quote_end, item.quote_text)
            for claim in selected_claims
            for item in claim.evidence_refs
        }
        for evidence in profile.evidence_refs:
            key = (evidence.chunk_id, evidence.quote_start, evidence.quote_end, evidence.quote_text)
            source_text = source_text_by_chunk_id.get(evidence.chunk_id)
            if (
                key not in allowed_evidence
                or source_text is None
                or evidence.quote_text is None
                or evidence.quote_text not in source_text
            ):
                raise ValueError(
                    "CampusContentProfileAgent evidence must be selected factual Claim evidence "
                    "from a source_chunk_ids-selected SourceChunk"
                )
        return profile


def _require_project_id(input_context: Mapping[str, object]) -> str:
    project_id = input_context.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("CampusContentProfileAgent requires nonblank project_id")
    return project_id


def _factual_claims(
    input_context: Mapping[str, object], project_id: str
) -> dict[str, ClaimProposalV1]:
    raw_claims = input_context.get("claim_proposals")
    raw_projects = input_context.get("claim_project_ids")
    if not isinstance(raw_claims, list) or not isinstance(raw_projects, Mapping):
        raise ValueError(
            "CampusContentProfileAgent requires claim_proposals and explicit claim_project_ids"
        )
    claims: dict[str, ClaimProposalV1] = {}
    for raw_claim in raw_claims:
        try:
            claim = (
                raw_claim
                if isinstance(raw_claim, ClaimProposalV1)
                else ClaimProposalV1.model_validate(raw_claim)
            )
        except ValidationError as exc:
            raise ValueError(
                "CampusContentProfileAgent requires valid ClaimProposalV1 values"
            ) from exc
        claim_id = claim.claim_id
        if (
            not isinstance(claim_id, str)
            or not claim_id.strip()
            or claim.claim_type != ClaimType.FACTUAL_ASSERTION
            or not claim.evidence_refs
            or raw_projects.get(claim_id) != project_id
            or claim_id in claims
        ):
            raise ValueError(
                "CampusContentProfileAgent requires unique same-project factual Claims "
                "with evidence"
            )
        claims[claim_id] = claim
    return claims


def _source_text_by_chunk_id(input_context: Mapping[str, object]) -> dict[str, str]:
    source_chunk_ids = input_context.get("source_chunk_ids")
    source_chunks = input_context.get("source_chunks")
    if (
        not isinstance(source_chunk_ids, list)
        or not all(isinstance(item, str) and item for item in source_chunk_ids)
        or len(source_chunk_ids) != len(set(source_chunk_ids))
        or not isinstance(source_chunks, list)
    ):
        raise ValueError("CampusContentProfileAgent requires unique SourceChunkV1 source_chunk_ids")
    chunks: dict[str, str] = {}
    for raw_chunk in source_chunks:
        try:
            chunk = (
                raw_chunk
                if isinstance(raw_chunk, SourceChunkV1)
                else SourceChunkV1.model_validate(raw_chunk)
            )
        except ValidationError as exc:
            raise ValueError(
                "CampusContentProfileAgent requires valid SourceChunkV1 source_chunks"
            ) from exc
        if chunk.chunk_id in chunks:
            raise ValueError("CampusContentProfileAgent source chunks must have unique ids")
        chunks[chunk.chunk_id] = chunk.text
    if set(chunks) != set(source_chunk_ids):
        raise ValueError(
            "CampusContentProfileAgent source_chunk_ids must exactly match source_chunks"
        )
    return {chunk_id: chunks[chunk_id] for chunk_id in source_chunk_ids}
