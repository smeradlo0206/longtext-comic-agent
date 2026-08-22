"""Canonical commit boundary for evidence-backed story data."""

from comic_agent.ports.storybible import StoryBibleCanonicalRepositoryPort
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import (
    EventProposalV1,
    TemporalRelation,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1
from comic_agent.schemas.storybible import CommitPlanV1
from comic_agent.services.storybible_validator import EvidenceLookup, StoryBibleValidator


class CommitService:
    """Only service allowed to promote validated data toward canonical storage."""

    def __init__(self, evidence_lookup: EvidenceLookup) -> None:
        self._evidence_lookup = evidence_lookup

    def validate_story_proposal_evidence(self, proposal: EventProposalV1) -> None:
        """Ensure every evidence reference resolves to a known SourceChunk."""

        for evidence_ref in proposal.evidence_refs:
            self._validate_evidence_ref(evidence_ref)

    def validate_temporal_relation_evidence(
        self, proposal: TemporalRelationProposalV1, project_id: str
    ) -> None:
        """Validate Timeline evidence before a temporal relation is persisted."""

        if proposal.relation == TemporalRelation.UNKNOWN and not proposal.evidence_refs:
            return
        StoryBibleValidator(self._evidence_lookup).validate_evidence_refs(
            proposal.evidence_refs,
            project_id=project_id,
            owner=f"temporal relation {proposal.proposal_id}",
        )

    def commit_storybible_plan(
        self,
        plan: CommitPlanV1,
        repository: StoryBibleCanonicalRepositoryPort,
    ) -> CommitPlanV1:
        """Validate a complete plan, then promote its updates idempotently."""

        validator = StoryBibleValidator(self._evidence_lookup)
        validator.validate_commit_plan(plan)
        committed_plan = repository.get_matching_committed_plan(plan)
        if committed_plan is not None:
            return committed_plan
        repository.preflight_commit_plan(plan)
        with repository.commit_unit_of_work():
            committed_plan = repository.get_matching_committed_plan(plan)
            if committed_plan is not None:
                return committed_plan
            effective_plan = repository.save_candidate_plan(plan)
            repository.preflight_commit_plan(effective_plan)
            validator.validate_commit_plan(
                effective_plan,
                canonical_profiles=repository.list_profiles(effective_plan.project_id),
                canonical_states=repository.list_states(effective_plan.project_id),
            )
            for update in effective_plan.updates:
                repository.apply_canonical_update(update, effective_plan.commit_plan_id)
            committed_plan = repository.save_committed_plan(effective_plan)
        return committed_plan

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

        has_range = evidence_ref.quote_start is not None and evidence_ref.quote_end is not None
        if has_range:
            quote_start = evidence_ref.quote_start
            quote_end = evidence_ref.quote_end
            if quote_start is None or quote_end is None:
                raise ValueError("Evidence quote range out of bounds")
            if quote_start < 0 or quote_end > len(chunk.text):
                raise ValueError("Evidence quote range out of bounds; range exceeds source chunk")
            if evidence_ref.quote_text is not None:
                if chunk.text[quote_start:quote_end] != evidence_ref.quote_text:
                    raise ValueError("Evidence quote range does not match quote_text")
        elif evidence_ref.quote_text is not None and evidence_ref.quote_text not in chunk.text:
            raise ValueError("Evidence quote_text not found in source chunk")
