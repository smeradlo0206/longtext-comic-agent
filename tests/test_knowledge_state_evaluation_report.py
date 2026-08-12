import json
from pathlib import Path

from comic_agent.schemas.evaluation import (
    KnowledgeStateEvaluationCaseBatchV1,
    KnowledgeStateEvaluationCaseV1,
    KnowledgeStateEvaluationRunFailureV1,
)
from comic_agent.schemas.narrative import KnowledgeStateProposalBatchV1
from comic_agent.services.knowledge_state_evaluator import build_knowledge_state_evaluation_report


def _case(case_id: str) -> KnowledgeStateEvaluationCaseV1:
    cases = json.loads(
        Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    return KnowledgeStateEvaluationCaseV1.model_validate(
        next(item for item in cases if item["case_id"] == case_id)
    )


def _expected_batch(case: KnowledgeStateEvaluationCaseV1, batch_id: str) -> (
    KnowledgeStateProposalBatchV1
):
    states = [
        {
            "proposal_id": f"report-{case.case_id}-{index}",
            "subject": {
                "mention_text": expected.subject_text,
                "entity_proposal_id": None,
                "resolution_status": expected.subject_resolution_status,
            },
            "target": {
                "target_kind": expected.target_kind,
                "target_text": expected.target_text,
                "proposal_id": None,
                "proposal_schema": None,
                "resolution_status": expected.target_resolution_status,
            },
            "epistemic_status": expected.epistemic_status,
            "epistemic_basis": expected.epistemic_basis,
            "valid_from": None,
            "valid_until": None,
            "reality_layer": "PRIMARY",
            "evidence_refs": [
                {"chunk_id": case.source_chunks[0].chunk_id, "quote_text": expected.evidence_quote}
            ],
            "confidence": 0.9,
        }
        for index, expected in enumerate(case.expected_states, start=1)
    ]
    return KnowledgeStateProposalBatchV1.model_validate({"batch_id": batch_id, "states": states})


def test_report_aggregates_case_results_and_evidence_independently() -> None:
    heard_case = _case("heard-world-fact-positive")
    empty_case = _case("empty-batch-baseline")

    report = build_knowledge_state_evaluation_report(
        [
            KnowledgeStateEvaluationCaseBatchV1(
                case_id=heard_case.case_id,
                batch=_expected_batch(heard_case, "report-heard"),
            ),
            KnowledgeStateEvaluationCaseBatchV1(
                case_id=empty_case.case_id,
                batch=_expected_batch(empty_case, "report-empty"),
            ),
        ],
        {heard_case.case_id: heard_case, empty_case.case_id: empty_case},
    )

    assert report.evaluated_case_count == 2
    assert report.passed_case_count == 2
    assert report.failed_case_count == 0
    assert report.overall_pass_rate == 1.0
    assert report.evidence_pass_rate == 1.0
    assert report.zero_output_case_count == 1
    assert report.zero_output_passed_count == 1
    assert report.failure_type_counts == {}
    assert {item.category for item in report.category_summaries} == {"HEARD", "EMPTY_BATCH"}


def test_report_counts_status_and_evidence_errors_separately() -> None:
    case = _case("heard-world-fact-positive")
    payload = _expected_batch(case, "report-invalid").model_dump(mode="json")
    payload["states"][0]["epistemic_status"] = "KNOWS"
    payload["states"][0]["epistemic_basis"] = "OBSERVED"
    batch = KnowledgeStateProposalBatchV1.model_validate(payload)

    report = build_knowledge_state_evaluation_report(
        [KnowledgeStateEvaluationCaseBatchV1(case_id=case.case_id, batch=batch)],
        {case.case_id: case},
    )

    assert report.passed_case_count == 0
    assert report.status_correct_count == 0
    assert report.target_kind_correct_count == 1
    assert report.evidence_pass_rate == 1.0
    assert report.failure_type_counts["WRONG_EPISTEMIC_STATUS"] == 1
    assert report.failure_type_counts["FORBIDDEN_STATE_EMITTED"] == 1


def test_report_keeps_one_run_failure_and_marks_full_attempt_ineligible() -> None:
    raw_cases = json.loads(
        Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    cases = [KnowledgeStateEvaluationCaseV1.model_validate(item) for item in raw_cases]
    failed_case = next(case for case in cases if case.case_id == "unaware-positive-null-temporal")
    evaluations = [
        KnowledgeStateEvaluationCaseBatchV1(
            case_id=case.case_id,
            batch=_expected_batch(case, f"report-all-{case.case_id}"),
        )
        for case in cases
        if case.case_id != failed_case.case_id
    ]
    run_failure = KnowledgeStateEvaluationRunFailureV1(
        case_id=failed_case.case_id,
        failure_category="PROVIDER_SCHEMA_VALIDATION",
        message="Provider output failed schema validation after one recovery retry.",
        diagnostics={
            "schema_error_kind": "validation_error",
            "schema_error_field_paths": ["states"],
            "expected_output_schema": "KnowledgeStateProposalBatchV1",
            "request_attempts": 2,
        },
    )

    report = build_knowledge_state_evaluation_report(
        evaluations,
        {case.case_id: case for case in cases},
        [run_failure],
    )

    assert report.attempted_case_count == 12
    assert report.evaluated_case_count == 11
    assert report.run_failed_case_count == 1
    assert report.is_complete is True
    assert report.acceptance_eligible is False
    assert report.run_failure_category_counts["PROVIDER_SCHEMA_VALIDATION"] == 1
    assert any(item.case_id == failed_case.case_id for item in report.run_failures)
