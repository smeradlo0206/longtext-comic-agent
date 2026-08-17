import pytest

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import ClaimProposalV1, EventProposalV1, StateChangeProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    DuplicateCandidateType,
    TimelineAnalysisInputV1,
    TimelineConflictCategory,
)

EVIDENCE = [EvidenceRefV1(chunk_id="chunk-1", quote_text="A source sentence.")]


def event(proposal_id: str, summary: str = "Chen hands Lin an umbrella.") -> EventProposalV1:
    return EventProposalV1(
        proposal_id=proposal_id,
        event_type="HANDOFF",
        summary=summary,
        participant_ids=["chen", "lin"],
        location_id="library",
        evidence_refs=EVIDENCE,
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def claim(claim_id: str, object_value: str) -> ClaimProposalV1:
    return ClaimProposalV1(
        claim_id=claim_id,
        subject_id="lin",
        predicate="location",
        object_value=object_value,
        asserted_by_entity_id="chen",
        evidence_refs=EVIDENCE,
        confidence=0.8,
        reality_layer=RealityLayer.PRIMARY,
    )


def test_timeline_agent_outputs_safe_unknown_relation_and_duplicate_candidate() -> None:
    analysis = TimelineAgent().run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            event_proposals=[event("event-1"), event("event-2")],
        )
    )

    assert analysis.status == "CANDIDATE"
    assert len(analysis.temporal_relations) == 1
    assert analysis.temporal_relations[0].relation == "UNKNOWN"
    assert analysis.temporal_relations[0].confidence == 0.0
    assert analysis.duplicate_candidates[0].candidate_type == DuplicateCandidateType.EVENT
    assert analysis.duplicate_candidates[0].proposal_ids == ["event-1", "event-2"]


def test_timeline_agent_reports_missing_event_and_contradictory_claims() -> None:
    state_change = StateChangeProposalV1(
        proposal_id="state-1",
        event_id="missing-event",
        target_entity_id="lin",
        attribute_path="appearance.hair",
        old_value="long",
        new_value="short",
        persistent=True,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=EVIDENCE,
        confidence=0.9,
    )
    analysis = TimelineAgent().run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            claim_proposals=[claim("claim-1", "library"), claim("claim-2", "dormitory")],
            state_change_proposals=[state_change],
        )
    )

    assert {conflict.category for conflict in analysis.conflicts} == {
        TimelineConflictCategory.MISSING_EVENT_REFERENCE,
        TimelineConflictCategory.CONTRADICTORY_CLAIMS,
    }


def test_timeline_agent_marks_exact_claims_as_duplicate_candidates() -> None:
    analysis = TimelineAgent().run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            claim_proposals=[claim("claim-1", "library"), claim("claim-2", "library")],
        )
    )

    assert analysis.duplicate_candidates[0].candidate_type == DuplicateCandidateType.CLAIM


def source_chunk() -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id="chunk-1",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text="Chen leaves before Lin arrives. They meet simultaneously at noon.",
        checksum="source-checksum",
    )


def llm_response(
    relation: str, evidence_ids: list[str] | None = None, confidence: float = 0.9
) -> dict[str, object]:
    return {
        "relation": relation,
        "supporting_evidence_ids": evidence_ids
        if evidence_ids is not None
        else ([] if relation == "UNKNOWN" else ["event_a_evidence_0"]),
        "confidence": confidence,
        "reasoning_summary": "The supplied sentence explicitly states the ordering.",
    }


def test_timeline_agent_llm_infers_explicit_before_from_selected_evidence() -> None:
    analysis = TimelineAgent(MockLLMProvider(llm_response("BEFORE"))).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1", "Chen leaves."), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert analysis.temporal_relations[0].relation == "BEFORE"
    assert analysis.temporal_relations[0].reasoning_summary is not None


def test_timeline_agent_preserves_requested_reverse_order_for_after() -> None:
    analysis = TimelineAgent(MockLLMProvider(llm_response("AFTER"))).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-2", "Lin arrives."), event("event-1", "Chen leaves.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert analysis.temporal_relations[0].relation == "AFTER"


def test_timeline_agent_llm_allows_explicit_simultaneous_and_unknown() -> None:
    simultaneous = TimelineAgent(
        MockLLMProvider(llm_response("SIMULTANEOUS", ["event_b_evidence_0"]))
    ).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1"), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )
    unknown = TimelineAgent(MockLLMProvider(llm_response("UNKNOWN", [], 0.98))).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1"), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert simultaneous.temporal_relations[0].relation == "SIMULTANEOUS"
    assert unknown.temporal_relations[0].relation == "UNKNOWN"
    assert unknown.temporal_relations[0].confidence == 0.98


def test_timeline_agent_rejects_unknown_evidence_id() -> None:
    with pytest.raises(ValueError, match="unknown evidence id"):
        TimelineAgent(MockLLMProvider(llm_response("BEFORE", ["invented_evidence_id"]))).run(
            TimelineAnalysisInputV1(
                project_id="project-1",
                mode="LLM",
                event_proposals=[event("event-1"), event("event-2")],
            ),
            source_chunks=[source_chunk()],
        )


def test_timeline_agent_llm_disabled_falls_back_to_rules() -> None:
    analysis = TimelineAgent(
        MockLLMProvider(llm_response("BEFORE")), llm_enabled=False
    ).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1"), event("event-2")],
        ),
        source_chunks=[source_chunk()],
    )

    assert analysis.temporal_relations[0].relation == "UNKNOWN"
