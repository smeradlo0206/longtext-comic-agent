import json
from pathlib import Path

import pytest

from comic_agent.schemas.evaluation import KnowledgeStateEvaluationCaseV1
from comic_agent.schemas.narrative import KnowledgeStateProposalBatchV1
from comic_agent.services.knowledge_state_evaluator import evaluate_knowledge_state_case


def _case(case_id: str) -> KnowledgeStateEvaluationCaseV1:
    cases = json.loads(
        Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    return KnowledgeStateEvaluationCaseV1.model_validate(
        next(item for item in cases if item["case_id"] == case_id)
    )


def test_evaluator_accepts_heard_world_fact_with_exact_evidence() -> None:
    case = _case("heard-world-fact-positive")
    batch = KnowledgeStateProposalBatchV1.model_validate(
        {
            "batch_id": "batch-1",
            "states": [
                {
                    "proposal_id": "unstable-id",
                    "subject": {
                        "mention_text": "林舟",
                        "entity_proposal_id": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "target_kind": "WORLD_FACT",
                        "target_text": "城门已经封锁",
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "epistemic_status": "HEARD",
                    "epistemic_basis": "HEARD",
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {"chunk_id": "fixture-heard-1", "quote_text": "林舟听掌柜说城门已经封锁。"}
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )

    result = evaluate_knowledge_state_case(case, batch)

    assert result.passed is True
    assert result.matched_expected_count == 1
    assert result.evidence_pass_rate == 1.0


def test_evaluator_rejects_rumor_wrapper_without_weakening_schema_validation() -> None:
    case = _case("disbelieves-rumor-content-boundary")
    batch = KnowledgeStateProposalBatchV1.model_validate(
        {
            "batch_id": "batch-2",
            "states": [
                {
                    "proposal_id": "unstable-id",
                    "subject": {
                        "mention_text": "林舟",
                        "entity_proposal_id": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "target_kind": "WORLD_FACT",
                        "target_text": "山中有鬼的传言",
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "epistemic_status": "DISBELIEVES",
                    "epistemic_basis": "STATED",
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {
                            "chunk_id": "fixture-disbelieves-1",
                            "quote_text": "林舟说：‘我不信山中有鬼。’",
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )

    result = evaluate_knowledge_state_case(case, batch)

    assert result.passed is False
    assert "WRONG_TARGET_TEXT" in result.failure_types


def test_evaluator_reports_a_valid_forbidden_state_before_missing_expected() -> None:
    case = _case("heard-world-fact-positive")
    batch = KnowledgeStateProposalBatchV1.model_validate(
        {
            "batch_id": "batch-3",
            "states": [
                {
                    "proposal_id": "unstable-id",
                    "subject": {
                        "mention_text": "林舟",
                        "entity_proposal_id": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "target_kind": "WORLD_FACT",
                        "target_text": "城门已经封锁",
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "epistemic_status": "KNOWS",
                    "epistemic_basis": "OBSERVED",
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {"chunk_id": "fixture-heard-1", "quote_text": "林舟听掌柜说城门已经封锁。"}
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )

    result = evaluate_knowledge_state_case(case, batch)

    assert result.passed is False
    assert "FORBIDDEN_STATE_EMITTED" in result.failure_types
    assert "WRONG_EPISTEMIC_STATUS" in result.failure_types


def _proposal_for_case(
    case: KnowledgeStateEvaluationCaseV1,
    *,
    target_kind: str | None = None,
    epistemic_basis: str | None = None,
    evidence_quote: str | None = None,
    quote_start: int | None = None,
    quote_end: int | None = None,
) -> KnowledgeStateProposalBatchV1:
    expected = case.expected_states[0]
    return KnowledgeStateProposalBatchV1.model_validate(
        {
            "batch_id": f"batch-{case.case_id}",
            "states": [
                {
                    "proposal_id": "contract-state-1",
                    "subject": {
                        "mention_text": expected.subject_text,
                        "entity_proposal_id": None,
                        "resolution_status": expected.subject_resolution_status,
                    },
                    "target": {
                        "target_kind": target_kind or expected.target_kind,
                        "target_text": expected.target_text,
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": expected.target_resolution_status,
                    },
                    "epistemic_status": expected.epistemic_status,
                    "epistemic_basis": epistemic_basis or expected.epistemic_basis,
                    "valid_from": None,
                    "valid_until": None,
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {
                            "chunk_id": case.source_chunks[0].chunk_id,
                            "quote_text": evidence_quote or expected.evidence_quote,
                            "quote_start": quote_start,
                            "quote_end": quote_end,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )


def test_evaluator_accepts_exact_quote_with_null_offsets() -> None:
    case = _case("suspects-world-fact-positive")

    result = evaluate_knowledge_state_case(case, _proposal_for_case(case))

    assert result.passed is True


def test_disbelief_fixture_requires_the_complete_verbatim_sentence() -> None:
    case = _case("disbelieves-rumor-content-boundary")

    complete_result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, evidence_quote="我不信山中有鬼。"),
    )
    truncated_result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, evidence_quote="我不信山中有鬼"),
    )

    assert complete_result.passed is True
    assert truncated_result.passed is False
    assert "EVIDENCE_QUOTE_MISMATCH" in truncated_result.failure_types


def test_disbelief_fixture_accepts_its_explicit_full_sentence_evidence_alternative() -> None:
    case = _case("disbelieves-rumor-content-boundary")

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, evidence_quote="林舟说：‘我不信山中有鬼。’"),
    )

    assert result.passed is True


def test_disbelief_fixture_rejects_an_unlisted_source_subquote() -> None:
    case = _case("disbelieves-rumor-content-boundary")

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, evidence_quote="林舟说："),
    )

    assert result.passed is False
    assert "EVIDENCE_QUOTE_MISMATCH" in result.failure_types


def test_evaluator_accepts_exact_python_half_open_offsets() -> None:
    case = _case("suspects-world-fact-positive")
    source = case.source_chunks[0].text
    quote = case.expected_states[0].evidence_quote
    start = source.index(quote)

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, quote_start=start, quote_end=start + len(quote)),
    )

    assert result.passed is True


@pytest.mark.parametrize(("start_delta", "end_delta"), [(1, 1), (0, -1)])
def test_evaluator_rejects_non_exact_offsets_without_auto_repair(
    start_delta: int, end_delta: int
) -> None:
    case = _case("suspects-world-fact-positive")
    source = case.source_chunks[0].text
    quote = case.expected_states[0].evidence_quote
    start = source.index(quote) + start_delta

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(
            case,
            quote_start=start,
            quote_end=start + len(quote) + end_delta,
        ),
    )

    assert result.passed is False
    assert "EVIDENCE_QUOTE_MISMATCH" in result.failure_types


def test_unresolved_reference_narrative_uses_unknown_basis() -> None:
    case = _case("unresolved-reference-boundary")

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, epistemic_basis="UNKNOWN"),
    )

    assert result.passed is True


def test_unaware_event_rejects_world_fact_target_kind() -> None:
    case = _case("unaware-positive-null-temporal")

    result = evaluate_knowledge_state_case(
        case,
        _proposal_for_case(case, target_kind="WORLD_FACT"),
    )

    assert result.passed is False
    assert "WRONG_TARGET_KIND" in result.failure_types


@pytest.mark.parametrize(
    ("case_id", "status", "target_kind", "target_text", "evidence_quote"),
    [
        (
            "suspects-world-fact-positive",
            "SUSPECTS",
            "WORLD_FACT",
            "守卫故意隐瞒了山路的位置",
            "林舟怀疑守卫故意隐瞒了山路的位置。",
        ),
        (
            "believes-positive",
            "BELIEVES",
            "WORLD_FACT",
            "失踪的哥哥仍然活着",
            "林舟坚信失踪的哥哥仍然活着。",
        ),
        (
            "unaware-positive-null-temporal",
            "UNAWARE",
            "EVENT",
            "妹妹已经离开小镇",
            "林舟不知道妹妹已经离开小镇。",
        ),
        (
            "disbelieves-rumor-content-boundary",
            "DISBELIEVES",
            "WORLD_FACT",
            "山中有鬼",
            "我不信山中有鬼。",
        ),
    ],
)
def test_evaluator_accepts_the_contract_for_narrated_states_and_shortest_verbatim_evidence(
    case_id: str,
    status: str,
    target_kind: str,
    target_text: str,
    evidence_quote: str,
) -> None:
    """Narrated mental states use UNKNOWN; a verbatim supported subquote is valid evidence."""

    case = _case(case_id)
    batch = KnowledgeStateProposalBatchV1.model_validate(
        {
            "batch_id": f"batch-{case_id}",
            "states": [
                {
                    "proposal_id": "contract-state-1",
                    "subject": {
                        "mention_text": "林舟",
                        "entity_proposal_id": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "target": {
                        "target_kind": target_kind,
                        "target_text": target_text,
                        "proposal_id": None,
                        "proposal_schema": None,
                        "resolution_status": "UNRESOLVED",
                    },
                    "epistemic_status": status,
                    "epistemic_basis": "UNKNOWN" if status != "DISBELIEVES" else "STATED",
                    "valid_from": None,
                    "valid_until": None,
                    "reality_layer": "PRIMARY",
                    "evidence_refs": [
                        {
                            "chunk_id": case.source_chunks[0].chunk_id,
                            "quote_text": evidence_quote,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
        }
    )

    result = evaluate_knowledge_state_case(case, batch)

    assert result.passed is True
    assert result.evidence_pass_rate == 1.0
