"""Canonical commit boundary for evidence-backed story data."""

from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1
from comic_agent.schemas.storybible import CommitPlanV1
from comic_agent.services.storybible_validator import EvidenceLookup, StoryBibleValidator


class CommitService:
    """Only service allowed to promote validated data toward canonical storage."""

    def __init__(self, evidence_lookup: EvidenceLookup) -> None:
        self._evidence_lookup = evidence_lookup

    def validate_story_proposal_evidence(self, proposal: EventProposalV1) -> None:
        """Ensure every evidence reference resolves to a known SourceChunk."""

        StoryBibleValidator(self._evidence_lookup).validate_evidence_refs(
            proposal.evidence_refs,
            owner=f"event proposal {proposal.proposal_id}",
        )

    def commit_storybible_plan(
        self,
        plan: CommitPlanV1,
        repository: StoryBibleRepository,
    ) -> CommitPlanV1:
        """Validate a complete plan, then promote its updates idempotently."""

        validator = StoryBibleValidator(self._evidence_lookup)
        validator.validate_commit_plan(plan)
        repository.preflight_commit_plan(plan)
        with repository.commit_unit_of_work():
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
