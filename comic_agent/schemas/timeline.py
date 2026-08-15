"""Proposal-only contracts for whole-text timeline analysis."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus, StrictBaseModel
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelationProposalV1,
)


class TimelineConflictCategory(StrEnum):
    """Conflict types detected without changing source proposals."""

    MISSING_EVENT_REFERENCE = "MISSING_EVENT_REFERENCE"
    CONTRADICTORY_CLAIMS = "CONTRADICTORY_CLAIMS"


class DuplicateCandidateType(StrEnum):
    """Kinds of candidates that may refer to the same narrative fact."""

    EVENT = "EVENT"
    CLAIM = "CLAIM"


class TimelineAnalysisMode(StrEnum):
    """Execution mode for a timeline analysis request."""

    RULES_ONLY = "RULES_ONLY"
    LLM = "LLM"


class TimelineConflictV1(StrictBaseModel):
    """Reviewable timeline conflict between proposal records."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    conflict_id: str = Field(description="Conflict id.")
    project_id: str = Field(description="Owning project id.")
    category: TimelineConflictCategory = Field(description="Conflict classification.")
    summary: str = Field(min_length=1, description="Human-readable conflict explanation.")
    affected_proposal_ids: list[str] = Field(min_length=1, description="Related proposal ids.")
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="Supporting evidence.")
    blocking: bool = Field(default=True, description="Whether review is required before promotion.")


class DuplicateCandidateV1(StrictBaseModel):
    """Possible duplicate that requires a later merge or human decision."""

    schema_version: Literal["1.0"] = Field(default="1.0", description="Schema version.")
    candidate_id: str = Field(description="Duplicate-candidate id.")
    project_id: str = Field(description="Owning project id.")
    candidate_type: DuplicateCandidateType = Field(description="Compared proposal type.")
    proposal_ids: list[str] = Field(
        min_length=2, max_length=2, description="Compared proposal ids."
    )
    reason: str = Field(min_length=1, description="Deterministic similarity reason.")
    evidence_refs: list[EvidenceRefV1] = Field(
        min_length=1, description="Evidence from both candidates."
    )
    confidence: float = Field(ge=0, le=1, description="Duplicate confidence.")

    @model_validator(mode="after")
    def proposal_ids_are_distinct(self) -> "DuplicateCandidateV1":
        if self.proposal_ids[0] == self.proposal_ids[1]:
            raise ValueError("duplicate candidate proposal_ids must be distinct")
        return self


class TimelineAnalysisInputV1(StrictBaseModel):
    """Whole-text candidate records supplied to the Timeline Agent."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    project_id: str = Field(description="Owning project id.")
    mode: TimelineAnalysisMode = Field(
        default=TimelineAnalysisMode.RULES_ONLY,
        description="RULES_ONLY preserves V1 behavior; LLM infers selected event pairs.",
    )
    event_proposals: list[EventProposalV1] = Field(default_factory=list)
    claim_proposals: list[ClaimProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_source_candidates(self) -> "TimelineAnalysisInputV1":
        if not (self.event_proposals or self.claim_proposals or self.state_change_proposals):
            raise ValueError("timeline analysis requires at least one proposal")
        has_evidence = any(proposal.evidence_refs for proposal in self.event_proposals)
        has_evidence = has_evidence or any(
            proposal.evidence_refs for proposal in self.claim_proposals
        )
        has_evidence = has_evidence or any(
            proposal.evidence_refs for proposal in self.state_change_proposals
        )
        if not has_evidence:
            raise ValueError("timeline analysis requires at least one evidence reference")
        return self


class TimelineAnalysisProposalV1(StrictBaseModel):
    """Candidate timeline analysis; no output is canonical story data."""

    schema_version: Literal["1.0", "1.1"] = Field(default="1.1", description="Schema version.")
    proposal_id: str = Field(description="Timeline-analysis proposal id.")
    project_id: str = Field(description="Owning project id.")
    status: RecordStatus = Field(default=RecordStatus.CANDIDATE)
    temporal_relations: list[TemporalRelationProposalV1] = Field(default_factory=list)
    conflicts: list[TimelineConflictV1] = Field(default_factory=list)
    duplicate_candidates: list[DuplicateCandidateV1] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefV1] = Field(min_length=1, description="Input-derived evidence.")
    confidence: float = Field(ge=0, le=1, description="Analysis confidence.")
