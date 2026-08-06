from pydantic import BaseModel

from comic_agent.schemas.narrative import ClaimProposalBatchV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.context_builder import AgentContext
from comic_agent.services.narrative_analyst_summary import (
    normalize_proposal_evidence,
    slim_input_context,
    validate_evidence_refs,
)


def _chunk(
    *,
    chunk_id: str,
    order: int,
    text: str,
    char_start: int,
) -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id=chunk_id,
        document_id="document-1",
        chapter_id=f"chapter-{order}",
        project_id="project-1",
        order=order,
        text=text,
        char_start=char_start,
        char_end=char_start + len(text),
        checksum=f"checksum-{order}",
    )


def _claim_batch(*, evidence: dict[str, object]) -> ClaimProposalBatchV1:
    return ClaimProposalBatchV1.model_validate(
        {
            "batch_id": "claim-batch-1",
            "claims": [
                {
                    "proposal_id": "claim-1",
                    "claim_type": "FACTUAL_ASSERTION",
                    "claim_text": "The narrator states a fact.",
                    "temporal_scope": "PRESENT",
                    "source_type": "NARRATOR",
                    "source_id": None,
                    "target_event_id": None,
                    "verification_status": "UNVERIFIED",
                    "evidence_refs": [evidence],
                    "confidence": 0.8,
                    "reality_layer": "PRIMARY",
                }
            ],
        }
    )


def test_slim_input_context_hides_document_global_char_ranges() -> None:
    chunk = _chunk(
        chunk_id="chunk-1",
        order=0,
        text="The local chunk text.",
        char_start=250,
    )

    payload = slim_input_context(
        AgentContext(
            project_id="project-1",
            chunks=[chunk],
            source_chunk_ids=[chunk.chunk_id],
        ),
        [chunk],
    )

    assert payload["source_chunks"] == [
        {
            "chunk_id": "chunk-1",
            "chapter_id": "chapter-0",
            "text": "The local chunk text.",
        }
    ]


def test_normalize_proposal_evidence_rebinds_a_unique_quote_and_uses_local_offsets() -> None:
    chunks = [
        _chunk(chunk_id="chunk-1", order=0, text="First chapter.", char_start=100),
        _chunk(
            chunk_id="chunk-2",
            order=1,
            text="Second chapter contains the exact claim.",
            char_start=300,
        ),
        _chunk(chunk_id="chunk-3", order=2, text="Third chapter.", char_start=500),
    ]
    proposal = _claim_batch(
        evidence={
            "chunk_id": "chunk-1",
            "quote_start": 315,
            "quote_end": 330,
            "quote_text": "the exact claim",
        }
    )

    result = normalize_proposal_evidence(proposal, chunks)

    assert isinstance(result.proposal, ClaimProposalBatchV1)
    evidence = result.proposal.claims[0].evidence_refs[0]
    assert evidence.chunk_id == "chunk-2"
    assert evidence.quote_start == 24
    assert evidence.quote_end == 39
    assert result.rebound_chunk_ids == 1
    assert result.rebased_quote_ranges == 1
    assert validate_evidence_refs([evidence], chunks)["evidence_validation_passed"] is True


def test_normalize_proposal_evidence_does_not_rebind_an_ambiguous_quote() -> None:
    chunks = [
        _chunk(chunk_id="chunk-1", order=0, text="Repeated phrase.", char_start=100),
        _chunk(chunk_id="chunk-2", order=1, text="Repeated phrase.", char_start=300),
        _chunk(chunk_id="chunk-3", order=2, text="Other text.", char_start=500),
    ]
    proposal = _claim_batch(
        evidence={
            "chunk_id": "chunk-3",
            "quote_text": "Repeated phrase",
        }
    )

    result = normalize_proposal_evidence(proposal, chunks)

    assert isinstance(result.proposal, BaseModel)
    evidence = result.proposal.claims[0].evidence_refs[0]
    assert evidence.chunk_id == "chunk-3"
    assert result.rebound_chunk_ids == 0
    assert validate_evidence_refs([evidence], chunks)["evidence_validation_passed"] is False
