import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from comic_agent.schemas.evaluation import (
    KnowledgeStateEvaluationCaseV1,
    KnowledgeStateEvaluationPolicyV1,
    KnowledgeStateExpectationV1,
    KnowledgeStateStateMatcherV1,
)


def test_evaluation_case_accepts_empty_expected_states_for_a_zero_output_case() -> None:
    case = KnowledgeStateEvaluationCaseV1.model_validate(
        json.loads(
            Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
                encoding="utf-8"
            )
        )[0]
    )

    assert case.case_id == "knows-observed-positive"


def test_all_bundled_evaluation_cases_are_versioned_and_synthetic() -> None:
    items = json.loads(
        Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    cases = [KnowledgeStateEvaluationCaseV1.model_validate(item) for item in items]

    assert len(cases) == 12
    assert all(case.schema_version == "1.1" for case in cases)
    assert all(case.fixture_origin == "SYNTHETIC" for case in cases)
    assert any(not case.expected_states for case in cases)


def test_evaluation_matcher_rejects_an_empty_forbidden_matcher() -> None:
    with pytest.raises(ValidationError, match="at least one condition"):
        KnowledgeStateStateMatcherV1()


def test_evaluation_policy_reuses_the_production_knowledge_state_enums() -> None:
    policy = KnowledgeStateEvaluationPolicyV1()

    assert policy.text_match_policy == "STRICT_NORMALIZED"
    assert policy.require_null_temporal_anchors_when_absent is True


def test_evaluation_expectation_allows_only_explicit_alternative_evidence_quotes() -> None:
    expectation = KnowledgeStateExpectationV1.model_validate(
        {
            "subject_text": "林舟",
            "subject_resolution_status": "UNRESOLVED",
            "epistemic_status": "DISBELIEVES",
            "epistemic_basis": "STATED",
            "target_kind": "WORLD_FACT",
            "target_text": "山中有鬼",
            "target_resolution_status": "UNRESOLVED",
            "evidence_quote": "我不信山中有鬼。",
            "allowed_evidence_quotes": ["林舟说：‘我不信山中有鬼。’"],
        }
    )

    assert expectation.allowed_evidence_quotes == ["林舟说：‘我不信山中有鬼。’"]


def test_v10_evaluation_case_rejects_evidence_quote_alternatives() -> None:
    item = json.loads(
        Path("comic_agent/fixtures/knowledge_state_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )[0]
    item["schema_version"] = "1.0"
    item["expected_states"][0]["allowed_evidence_quotes"] = ["另一段完整原文。"]

    with pytest.raises(ValidationError, match="does not support allowed evidence quotes"):
        KnowledgeStateEvaluationCaseV1.model_validate(item)
