"""Deterministic Review Gate 2 service tests."""

from inspect import signature

import pytest

from comic_agent.schemas import (
    AggregatedEntityProposalV1,
    AggregatedEventProposalV1,
    AggregatedKnowledgeStateProposalV1,
    AggregatedStateChangeProposalV1,
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    EvidenceRefV1,
    KnowledgeStateProposalV1,
    NarrativeAnalysisProposalSourceV1,
    NarrativeAnalysisResultV1,
    RelationshipSignalProposalV1,
    ReviewGate2PolicyV1,
    ReviewGate2ResultV1,
    ReviewIssueCode,
    SourceChunkV1,
    StateChangeProposalV1,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_analysis_aggregation import aggregate_narrative_analysis
from comic_agent.services.review_gate2_service import (
    ReviewGate2Service,
    ReviewGate2ServiceContext,
    build_review_gate2_input,
)


def _evidence(chunk_id: str = "chunk-1", quote: str = "source evidence") -> dict[str, object]:
    return {"chunk_id": chunk_id, "quote_text": quote}


def _chunk(text: str = "Lin source evidence.") -> SourceChunkV1:
    return SourceChunkV1(
        chunk_id="chunk-1",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text=text,
        checksum=checksum_text(text),
    )


def _event(proposal_id: str = "event-1") -> EventProposalV1:
    return EventProposalV1(
        proposal_id=proposal_id,
        event_type="OBSERVATION",
        summary="Lin observes the gate.",
        evidence_refs=[_evidence()],
        confidence=0.9,
        reality_layer="PRIMARY",
    )


def _entity(proposal_id: str = "entity-1") -> EntityProposalV1:
    return EntityProposalV1(
        proposal_id=proposal_id,
        entity_type="CHARACTER",
        canonical_name="Lin",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )


def _claim(proposal_id: str = "claim-1") -> ClaimProposalV1:
    return ClaimProposalV1(
        proposal_id=proposal_id,
        claim_type="FACTUAL_ASSERTION",
        claim_text="The gate is closed.",
        temporal_scope="PRESENT",
        source_type="NARRATOR",
        verification_status="UNVERIFIED",
        evidence_refs=[_evidence()],
        confidence=0.9,
        reality_layer="PRIMARY",
    )


def _knowledge(proposal_id: str = "knowledge-1") -> KnowledgeStateProposalV1:
    return KnowledgeStateProposalV1(
        proposal_id=proposal_id,
        subject={
            "mention_text": "Lin",
            "entity_proposal_id": None,
            "resolution_status": "UNRESOLVED",
        },
        target={
            "target_text": "The gate is closed.",
            "target_kind": "WORLD_FACT",
            "proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        epistemic_status="SUSPECTS",
        epistemic_basis="UNKNOWN",
        reality_layer="PRIMARY",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )


def _state_change(proposal_id: str = "state-change-1") -> StateChangeProposalV1:
    return StateChangeProposalV1(
        proposal_id=proposal_id,
        event={
            "event_summary": "Lin is injured.",
            "event_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        target={
            "mention_text": "Lin",
            "target_kind": "CHARACTER",
            "entity_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        attribute_path="health.injury",
        old_value=None,
        new_value="injured",
        persistent=False,
        reality_layer="PRIMARY",
        evidence_refs=[_evidence()],
        new_value_evidence_indexes=[0],
        persistence_evidence_indexes=[],
        confidence=0.9,
    )


def _relationship(proposal_id: str = "relationship-1") -> RelationshipSignalProposalV1:
    def participant(text: str) -> dict[str, object]:
        return {
            "mention_text": text,
            "participant_kind": "CHARACTER",
            "resolution_status": "UNRESOLVED",
            "entity_proposal_id": None,
            "proposal_schema": None,
        }

    return RelationshipSignalProposalV1(
        proposal_id=proposal_id,
        subject=participant("Lin"),
        counterpart=participant("Lan"),
        relationship_domain="TRUST",
        relationship_kind="TRUSTS",
        directionality="DIRECTED",
        signal_effect="PRESENT",
        assertion_polarity="AFFIRMED",
        evidence_basis="NARRATED",
        support_level="EXPLICIT",
        temporal_anchor={
            "valid_from": None,
            "valid_until": None,
            "anchor_text": None,
            "resolution_status": "UNRESOLVED",
            "event_proposal_id": None,
            "proposal_schema": None,
        },
        reality_layer="PRIMARY",
        evidence_refs=[_evidence()],
        confidence=0.9,
    )


def _result_with_all_modes() -> NarrativeAnalysisResultV1:
    proposals = [
        ("event_extraction", _event()),
        ("entity_extraction", _entity()),
        ("claim_extraction", _claim()),
        ("knowledge_state_extraction", _knowledge()),
        ("state_change_extraction", _state_change()),
        ("relationship_signal_extraction", _relationship()),
    ]
    sources = [
        NarrativeAnalysisProposalSourceV1(
            mode=mode, agent_run_id=f"agent-{index}", proposal=proposal
        )
        for index, (mode, proposal) in enumerate(proposals, 1)
    ]
    return aggregate_narrative_analysis(sources, analysis_run_id="analysis-1")


def _context(
    *, include_chunk: bool = True, known_runs: set[str] | None = None
) -> ReviewGate2ServiceContext:
    return ReviewGate2ServiceContext(
        source_chunks=[_chunk()] if include_chunk else [],
        known_agent_run_ids=(
            {f"agent-{index}" for index in range(1, 7)} if known_runs is None else known_runs
        ),
    )


def _event_result() -> NarrativeAnalysisResultV1:
    return NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=_event(), agent_run_ids=["agent-1"], evidence_refs=[_evidence()]
            )
        ],
    )


def _semantic_review_payload(value: ReviewGate2ResultV1) -> dict[str, object]:
    """Remove audit timestamps only; every decision-relevant field must remain stable."""

    def without_created_at(item: object) -> object:
        if isinstance(item, dict):
            return {
                key: without_created_at(child)
                for key, child in item.items()
                if key != "created_at"
            }
        if isinstance(item, list):
            return [without_created_at(child) for child in item]
        return item

    payload = value.model_dump(mode="json")
    assert isinstance(payload, dict)
    return without_created_at(payload)  # type: ignore[return-value]


def test_empty_result_is_completed_with_empty_approved_bundle() -> None:
    result = NarrativeAnalysisResultV1(analysis_run_id="analysis-1")
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=[],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(review_input)

    assert isinstance(reviewed, ReviewGate2ResultV1)
    assert reviewed.status == "COMPLETED"
    assert reviewed.total_count == 0
    assert reviewed.approved_bundle is not None
    assert reviewed.approved_bundle.approved_proposals == []


def test_build_input_flattens_all_six_modes_and_approves_them() -> None:
    result = _result_with_all_modes()
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    assert [str(item.mode) for item in review_input.proposals] == [
        "event_extraction",
        "entity_extraction",
        "claim_extraction",
        "knowledge_state_extraction",
        "state_change_extraction",
        "relationship_signal_extraction",
    ]
    reviewed = ReviewGate2Service().review(review_input, _context())

    assert reviewed.status == "COMPLETED"
    assert reviewed.approved_count == 6
    assert reviewed.rejected_count == 0
    assert reviewed.needs_human_review_count == 0
    assert reviewed.approved_bundle is not None
    assert len(reviewed.approved_bundle.approved_proposals) == 6


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda envelope: envelope.model_copy(
                update={"aggregated_evidence_refs": [_evidence(quote="missing")]}
            ),
            ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND,
        ),
        (
            lambda envelope: envelope.model_copy(
                update={"aggregated_evidence_refs": [_evidence("outside")]}
            ),
            ReviewIssueCode.EVIDENCE_OUTSIDE_ANALYSIS_SCOPE,
        ),
        (
            lambda envelope: envelope.model_copy(
                update={"aggregated_evidence_refs": [_evidence("chunk-1", "source")]}
            ),
            ReviewIssueCode.EVIDENCE_MISSING,
        ),
        (
            lambda envelope: envelope.model_copy(
                update={
                    "aggregated_evidence_refs": [
                        EvidenceRefV1(
                            chunk_id="chunk-1",
                            quote_text="source evidence",
                            quote_start=0,
                            quote_end=3,
                        )
                    ]
                }
            ),
            ReviewIssueCode.EVIDENCE_OFFSET_MISMATCH,
        ),
    ],
)
def test_evidence_failures_reject_without_repair(mutation, expected_code) -> None:
    result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=_event(), agent_run_ids=["agent-1"], evidence_refs=[_evidence()]
            )
        ],
    )
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )
    review_input = review_input.model_copy(
        update={"proposals": [mutation(review_input.proposals[0])]}
    )

    reviewed = ReviewGate2Service().review(review_input, _context(known_runs={"agent-1"}))

    assert reviewed.status == "COMPLETED"
    assert reviewed.rejected_count == 1
    assert reviewed.approved_bundle is not None
    assert reviewed.approved_bundle.approved_proposals == []
    assert expected_code in {issue.code for issue in reviewed.decisions[0].issues}
    if expected_code == ReviewIssueCode.EVIDENCE_MISSING:
        assert reviewed.decisions[0].evidence_reviews[0].status == "PASSED"
    else:
        assert reviewed.decisions[0].evidence_reviews[0].status == "FAILED"


def test_missing_agent_run_provenance_is_blocking() -> None:
    result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=_event(), agent_run_ids=["agent-1"], evidence_refs=[_evidence()]
            )
        ],
    )
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(review_input, _context(known_runs=set()))

    assert reviewed.rejected_count == 1
    assert ReviewIssueCode.AGENT_RUN_NOT_FOUND in {
        issue.code for issue in reviewed.decisions[0].issues
    }


def test_unique_exact_reference_is_recorded_without_mutating_proposal() -> None:
    proposal = _state_change()
    result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        entities=[
            AggregatedEntityProposalV1(
                proposal=_entity(), agent_run_ids=["agent-entity"], evidence_refs=[_evidence()]
            )
        ],
        state_changes=[
            AggregatedStateChangeProposalV1(
                proposal=proposal,
                agent_run_ids=["agent-state"],
                evidence_refs=[_evidence()],
            )
        ],
    )
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(
        review_input,
        _context(known_runs={"agent-entity", "agent-state"}),
    )

    assert reviewed.status == "COMPLETED"
    state_decision = next(
        item for item in reviewed.decisions if item.proposal_id == proposal.proposal_id
    )
    assert state_decision.reference_decisions[1].status == "RESOLVED"
    assert state_decision.reference_decisions[1].resolution_basis == "EXACT_UNIQUE_MENTION"
    assert proposal.target is not None
    assert proposal.target.resolution_status == "UNRESOLVED"


def test_multiple_exact_reference_candidates_require_human_review() -> None:
    result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        entities=[
            AggregatedEntityProposalV1(
                proposal=_entity("entity-1"),
                agent_run_ids=["agent-1"],
                evidence_refs=[_evidence()],
            ),
            AggregatedEntityProposalV1(
                proposal=_entity("entity-2"),
                agent_run_ids=["agent-2"],
                evidence_refs=[_evidence()],
            ),
        ],
        knowledge_states=[
            AggregatedKnowledgeStateProposalV1(
                proposal=_knowledge(),
                agent_run_ids=["agent-3"],
                evidence_refs=[_evidence()],
            )
        ],
    )
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(
        review_input,
        _context(known_runs={"agent-1", "agent-2", "agent-3"}),
    )

    assert reviewed.status == "NEEDS_HUMAN_REVIEW"
    assert reviewed.approved_bundle is None
    knowledge_decision = next(
        item for item in reviewed.decisions if item.proposal_id == "knowledge-1"
    )
    assert knowledge_decision.decision == "NEEDS_HUMAN_REVIEW"
    assert ReviewIssueCode.AMBIGUOUS_ENTITY_REFERENCE in {
        issue.code for issue in knowledge_decision.issues
    }


def test_exact_duplicate_content_is_rejected_without_merging_proposals() -> None:
    result = NarrativeAnalysisResultV1(
        analysis_run_id="analysis-1",
        events=[
            AggregatedEventProposalV1(
                proposal=_event("event-1"),
                agent_run_ids=["agent-1"],
                evidence_refs=[_evidence()],
            ),
            AggregatedEventProposalV1(
                proposal=_event("event-2"),
                agent_run_ids=["agent-2"],
                evidence_refs=[_evidence()],
            ),
        ],
    )
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(
        review_input, _context(known_runs={"agent-1", "agent-2"})
    )

    assert reviewed.status == "COMPLETED"
    assert reviewed.rejected_count == 2
    assert reviewed.approved_bundle is not None
    assert reviewed.approved_bundle.approved_proposals == []
    assert all(
        ReviewIssueCode.EXACT_DUPLICATE in {issue.code for issue in decision.issues}
        for decision in reviewed.decisions
    )


def test_duplicate_context_chunk_ids_fail_without_selecting_one() -> None:
    review_input = build_review_gate2_input(
        result=_event_result(),
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )
    context = ReviewGate2ServiceContext(
        source_chunks=[_chunk(), _chunk("Other source evidence.")],
        known_agent_run_ids={"agent-1"},
    )

    reviewed = ReviewGate2Service().review(review_input, context)

    assert reviewed.status == "FAILED"
    assert reviewed.approved_bundle is None
    assert reviewed.decisions == []
    assert [issue.code for issue in reviewed.execution_issues] == [
        ReviewIssueCode.REVIEW_EXECUTION_FAILED
    ]
    assert "Other source evidence." not in reviewed.execution_issues[0].sanitized_message


def test_out_of_scope_context_chunk_fails_before_partial_review() -> None:
    review_input = build_review_gate2_input(
        result=_event_result(),
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )
    extra_chunk = _chunk("Out-of-scope source evidence.").model_copy(
        update={"chunk_id": "chunk-outside"}
    )
    context = ReviewGate2ServiceContext(
        source_chunks=[_chunk(), extra_chunk], known_agent_run_ids={"agent-1"}
    )

    reviewed = ReviewGate2Service().review(review_input, context)

    assert reviewed.status == "FAILED"
    assert reviewed.approved_bundle is None
    assert reviewed.decisions == []
    assert [issue.code for issue in reviewed.execution_issues] == [
        ReviewIssueCode.REVIEW_EXECUTION_FAILED
    ]
    assert "Out-of-scope source evidence." not in reviewed.execution_issues[0].sanitized_message


def test_missing_evidence_chunk_is_proposal_rejection_not_context_failure() -> None:
    review_input = build_review_gate2_input(
        result=_event_result(),
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )

    reviewed = ReviewGate2Service().review(
        review_input,
        ReviewGate2ServiceContext(known_agent_run_ids={"agent-1"}),
    )

    assert reviewed.status == "COMPLETED"
    assert reviewed.rejected_count == 1
    assert reviewed.execution_issues == []
    assert ReviewIssueCode.EVIDENCE_CHUNK_NOT_FOUND in {
        issue.code for issue in reviewed.decisions[0].issues
    }


def test_agent_run_mapping_outside_known_scope_is_execution_failure() -> None:
    review_input = build_review_gate2_input(
        result=_event_result(),
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1"],
        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
    )
    context = ReviewGate2ServiceContext(
        source_chunks=[_chunk()],
        known_agent_run_ids={"agent-1"},
        agent_run_analysis_run_ids={"agent-outside": "analysis-1"},
    )

    reviewed = ReviewGate2Service().review(review_input, context)

    assert reviewed.status == "FAILED"
    assert reviewed.approved_bundle is None
    assert [issue.code for issue in reviewed.execution_issues] == [
        ReviewIssueCode.REVIEW_EXECUTION_FAILED
    ]


def test_build_input_has_no_ignored_agent_run_ids_parameter() -> None:
    assert "agent_run_ids" not in signature(build_review_gate2_input).parameters


@pytest.mark.parametrize(
    "scenario",
    ["approved", "rejected", "needs_human_review", "failed"],
)
def test_repeated_review_is_stable_except_audit_timestamps(scenario: str) -> None:
    if scenario == "approved":
        review_input = build_review_gate2_input(
            result=_event_result(),
            project_id="project-1",
            document_id="document-1",
            allowed_chunk_ids=["chunk-1"],
            policy=ReviewGate2PolicyV1(policy_id="policy-1"),
        )
        context = _context(known_runs={"agent-1"})
    elif scenario == "rejected":
        review_input = build_review_gate2_input(
            result=_event_result(),
            project_id="project-1",
            document_id="document-1",
            allowed_chunk_ids=["chunk-1"],
            policy=ReviewGate2PolicyV1(policy_id="policy-1"),
        ).model_copy(
            update={
                "proposals": [
                    build_review_gate2_input(
                        result=_event_result(),
                        project_id="project-1",
                        document_id="document-1",
                        allowed_chunk_ids=["chunk-1"],
                        policy=ReviewGate2PolicyV1(policy_id="policy-1"),
                    ).proposals[0].model_copy(
                        update={"aggregated_evidence_refs": [_evidence(quote="missing")]}
                    )
                ]
            }
        )
        context = _context(known_runs={"agent-1"})
    elif scenario == "needs_human_review":
        result = NarrativeAnalysisResultV1(
            analysis_run_id="analysis-1",
            entities=[
                AggregatedEntityProposalV1(
                    proposal=_entity("entity-1"),
                    agent_run_ids=["agent-1"],
                    evidence_refs=[_evidence()],
                ),
                AggregatedEntityProposalV1(
                    proposal=_entity("entity-2"),
                    agent_run_ids=["agent-2"],
                    evidence_refs=[_evidence()],
                ),
            ],
            knowledge_states=[
                AggregatedKnowledgeStateProposalV1(
                    proposal=_knowledge(),
                    agent_run_ids=["agent-3"],
                    evidence_refs=[_evidence()],
                )
            ],
        )
        review_input = build_review_gate2_input(
            result=result,
            project_id="project-1",
            document_id="document-1",
            allowed_chunk_ids=["chunk-1"],
            policy=ReviewGate2PolicyV1(policy_id="policy-1"),
        )
        context = _context(known_runs={"agent-1", "agent-2", "agent-3"})
    else:
        review_input = build_review_gate2_input(
            result=_event_result(),
            project_id="project-1",
            document_id="document-1",
            allowed_chunk_ids=["chunk-1"],
            policy=ReviewGate2PolicyV1(policy_id="policy-1"),
        )
        context = ReviewGate2ServiceContext(
            source_chunks=[_chunk(), _chunk("Other source evidence.")],
            known_agent_run_ids={"agent-1"},
        )

    service = ReviewGate2Service()
    first = service.review(review_input, context)
    second = service.review(review_input, context)

    assert first.review_run_id == second.review_run_id
    assert _semantic_review_payload(first) == _semantic_review_payload(second)
