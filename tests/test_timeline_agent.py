import pytest

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.agents.timeline_output_normalizer import TIMELINE_PAIR_OUTPUT_NORMALIZER
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import ClaimProposalV1, EventProposalV1, StateChangeProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    DuplicateCandidateType,
    TimelineAnalysisInputV1,
    TimelineConflictCategory,
    TimelinePairInferenceV1,
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


def modern_claim(proposal_id: str, object_value: str) -> ClaimProposalV1:
    return ClaimProposalV1(
        schema_version="1.3",
        proposal_id=proposal_id,
        claim_id=None,
        subject_id="lin",
        predicate="location",
        object_value=object_value,
        asserted_by_entity_id="chen",
        claim_type="FACTUAL_ASSERTION",
        claim_text=f"Lin is in the {object_value}.",
        temporal_scope="PRESENT",
        source_type="NARRATOR",
        verification_status="UNVERIFIED",
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


def test_timeline_agent_uses_proposal_ids_for_duplicate_claims_without_legacy_ids() -> None:
    analysis = TimelineAgent().run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            claim_proposals=[
                modern_claim("proposal-1", "library"),
                modern_claim("proposal-2", "library"),
            ],
        )
    )

    duplicate = analysis.duplicate_candidates[0]
    assert duplicate.candidate_type == DuplicateCandidateType.CLAIM
    assert duplicate.proposal_ids == ["proposal-1", "proposal-2"]
    assert None not in duplicate.proposal_ids


def test_timeline_agent_uses_proposal_ids_for_contradictory_claims_without_legacy_ids() -> None:
    analysis = TimelineAgent().run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            claim_proposals=[
                modern_claim("proposal-1", "library"),
                modern_claim("proposal-2", "dormitory"),
            ],
        )
    )

    conflict = next(
        item
        for item in analysis.conflicts
        if item.category == TimelineConflictCategory.CONTRADICTORY_CLAIMS
    )
    assert conflict.affected_proposal_ids == ["proposal-1", "proposal-2"]
    assert None not in conflict.affected_proposal_ids


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
    relation: str, _quote: str | None = "Chen leaves before Lin arrives."
) -> dict[str, object]:
    return {
        "relation": relation,
        "evidence_indexes": [] if relation == "UNKNOWN" else [0],
        "confidence": 0.9,
        "reasoning_summary": "The supplied sentence explicitly states the ordering.",
    }


def test_timeline_agent_llm_infers_explicit_before() -> None:
    provider = MockLLMProvider(llm_response("BEFORE"))
    analysis = TimelineAgent(provider).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1", "Chen leaves."), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert analysis.temporal_relations[0].relation == "BEFORE"
    assert analysis.temporal_relations[0].source_event_id == "event-1"
    assert analysis.temporal_relations[0].target_event_id == "event-2"
    assert analysis.temporal_relations[0].evidence_refs == EVIDENCE
    assert analysis.temporal_relations[0].reasoning_summary is not None


def test_timeline_agent_preserves_requested_reverse_order_for_after() -> None:
    response = llm_response("AFTER")
    analysis = TimelineAgent(MockLLMProvider(response)).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-2", "Lin arrives."), event("event-1", "Chen leaves.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert analysis.temporal_relations[0].relation == "AFTER"
    assert analysis.temporal_relations[0].source_event_id == "event-2"
    assert analysis.temporal_relations[0].target_event_id == "event-1"


def test_timeline_agent_llm_allows_explicit_simultaneous_and_unknown() -> None:
    simultaneous = TimelineAgent(
        MockLLMProvider(llm_response("SIMULTANEOUS", "They meet simultaneously at noon."))
    ).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1"), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )
    unknown = TimelineAgent(MockLLMProvider(llm_response("UNKNOWN", None))).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1"), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert simultaneous.temporal_relations[0].relation == "SIMULTANEOUS"
    assert unknown.temporal_relations[0].relation == "UNKNOWN"


class _SchemaRepairProvider:
    def __init__(self, *, fail_twice: bool = False) -> None:
        self.calls = 0
        self.requests: list[dict[str, object]] = []
        self.output_models: list[type[object]] = []
        self.fail_twice = fail_twice

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(request)
        self.output_models.append(output_model)
        if self.calls == 1 or self.fail_twice:
            raise ProviderResponseError(
                "sanitized schema failure",
                diagnostics={
                    "schema_error_field_paths": ["evidence_indexes.0"],
                    "schema_error_rule_codes": ["TIMELINE_EVIDENCE_INDEX_INVALID"],
                    "expected_output_schema": "TimelinePairInferenceV1",
                },
            )
        return output_model.model_validate(llm_response("BEFORE"))


def test_timeline_agent_uses_small_pair_contract_and_one_safe_schema_repair() -> None:
    provider = _SchemaRepairProvider()

    analysis = TimelineAgent(provider).run(
        TimelineAnalysisInputV1(
            project_id="project-1",
            mode="LLM",
            event_proposals=[event("event-1", "Chen leaves."), event("event-2", "Lin arrives.")],
        ),
        source_chunks=[source_chunk()],
    )

    assert provider.calls == 2
    assert provider.output_models == [TimelinePairInferenceV1, TimelinePairInferenceV1]
    repair_messages = provider.requests[1]["messages"]
    assert isinstance(repair_messages, list)
    assert "TIMELINE_EVIDENCE_INDEX_INVALID" in str(repair_messages)
    assert "sanitized schema failure" not in str(repair_messages)
    assert analysis.temporal_relations[0].evidence_refs == EVIDENCE


def test_timeline_pair_prompt_requests_a_json_data_answer_not_a_field_description() -> None:
    first = event("event-1", "Chen leaves.")
    second = event("event-2", "Lin arrives.")
    agent = TimelineAgent()

    request = agent._request_for_pair(  # noqa: SLF001 - contract regression coverage
        first,
        second,
        {"chunk-1": source_chunk()},
        EVIDENCE,
    )

    messages = request["messages"]
    assert request["output_normalizer"] == TIMELINE_PAIR_OUTPUT_NORMALIZER
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "JSON data object" in system_prompt
    assert "not a description of fields" in system_prompt
    assert '"relation"' in system_prompt
    assert '"evidence_indexes"' in system_prompt
    assert "JSON Schema" not in system_prompt


def test_timeline_agent_stops_after_one_schema_repair() -> None:
    provider = _SchemaRepairProvider(fail_twice=True)

    with pytest.raises(ProviderResponseError):
        TimelineAgent(provider).run(
            TimelineAnalysisInputV1(
                project_id="project-1",
                mode="LLM",
                event_proposals=[event("event-1"), event("event-2")],
            ),
            source_chunks=[source_chunk()],
        )

    assert provider.calls == 2
