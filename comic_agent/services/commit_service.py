"""Minimal commit service gate for proposal validation."""

from typing import Protocol

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1


class EvidenceLookup(Protocol):
    """Repository capability needed by CommitService."""

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        """Return a source chunk by id."""


class CommitService:
    """Only service allowed to promote validated data toward canonical storage."""

    def __init__(self, evidence_lookup: EvidenceLookup) -> None:
        self._evidence_lookup = evidence_lookup

    def validate_story_proposal_evidence(self, proposal: EventProposalV1) -> None:
        """Ensure every evidence reference resolves to a known SourceChunk."""

        for evidence_ref in proposal.evidence_refs:
            self._validate_evidence_ref(evidence_ref)

    def commit_source_document(self, document: SourceDocumentV1) -> SourceDocumentV1:
        """Return source document as already canonical after repository persistence."""

        return document

    def commit_source_chapter(self, chapter: SourceChapterV1) -> SourceChapterV1:
        """Return source chapter as already canonical after repository persistence."""

        return chapter

    def commit_source_chunk(self, chunk: SourceChunkV1) -> SourceChunkV1:
        """Return source chunk as already canonical after repository persistence."""

        return chunk

    def commit_story_event(self, proposal: EventProposalV1) -> None:
        """Reject story proposal promotion until story canonical rules exist."""

        self.validate_story_proposal_evidence(proposal)
        raise NotImplementedError("Story proposal canonical commits are not implemented in phase 1")

    def _validate_evidence_ref(self, evidence_ref: EvidenceRefV1) -> None:
        chunk = self._evidence_lookup.get_chunk(evidence_ref.chunk_id)
        if chunk is None:
            raise ValueError(f"EvidenceRef chunk not found: {evidence_ref.chunk_id}")

        if evidence_ref.quote_start is None:
            if evidence_ref.quote_text is not None and evidence_ref.quote_text not in chunk.text:
                raise ValueError("EvidenceRef quote_text does not match source chunk")
            return

        quote_end = evidence_ref.quote_end
        if quote_end is None:
            raise ValueError("EvidenceRef quote range is incomplete")
        if quote_end > len(chunk.text):
            raise ValueError("EvidenceRef quote range exceeds source chunk")

        source_quote = chunk.text[evidence_ref.quote_start : quote_end]
        if evidence_ref.quote_text is not None and evidence_ref.quote_text != source_quote:
            raise ValueError("EvidenceRef quote_text does not match source chunk")
