"""Pure, deterministic evaluator and aggregate reporter for Knowledge State fixtures."""

import unicodedata
from collections import Counter

from comic_agent.schemas.evaluation import (
    KnowledgeStateEvaluationCaseBatchV1,
    KnowledgeStateEvaluationCaseV1,
    KnowledgeStateEvaluationCategory,
    KnowledgeStateEvaluationCategorySummaryV1,
    KnowledgeStateEvaluationFailureType,
    KnowledgeStateEvaluationFailureV1,
    KnowledgeStateEvaluationReportV1,
    KnowledgeStateEvaluationResultV1,
    KnowledgeStateEvaluationRunFailureCategory,
    KnowledgeStateEvaluationRunFailureV1,
    KnowledgeStateExpectationResultV1,
    KnowledgeStateExpectationV1,
    KnowledgeStateStateMatcherV1,
    KnowledgeTemporalAnchorExpectationV1,
)
from comic_agent.schemas.narrative import (
    KnowledgeStateProposalBatchV1,
    KnowledgeStateProposalV1,
    KnowledgeTemporalAnchorV1,
)


def evaluate_knowledge_state_case(
    case: KnowledgeStateEvaluationCaseV1,
    batch: KnowledgeStateProposalBatchV1,
) -> KnowledgeStateEvaluationResultV1:
    """Compare one batch to one fixture without providers, persistence, or fuzzy matching."""

    actual_states = batch.states
    unmatched_actual = set(range(len(actual_states)))
    expectation_results: list[KnowledgeStateExpectationResultV1] = []
    failures: list[KnowledgeStateEvaluationFailureV1] = []
    evidence_pass_count = 0
    for expected_index, expected in enumerate(case.expected_states):
        if any(_evidence_matches(case, expected, actual) for actual in actual_states):
            evidence_pass_count += 1
        matched_index = next(
            (
                actual_index
                for actual_index in unmatched_actual
                if _matches_expected(case, expected, actual_states[actual_index])
            ),
            None,
        )
        if matched_index is None:
            failure_types = _expected_failure_types(case, expected, actual_states)
            expectation_results.append(
                KnowledgeStateExpectationResultV1(
                    expected_index=expected_index,
                    passed=False,
                    failure_types=failure_types,
                )
            )
            for failure_type in failure_types:
                failures.append(
                    KnowledgeStateEvaluationFailureV1(
                        failure_type=failure_type,
                        expected_index=expected_index,
                        detail="Expected Knowledge State was not matched.",
                    )
                )
            continue
        unmatched_actual.remove(matched_index)
        expectation_results.append(
            KnowledgeStateExpectationResultV1(
                expected_index=expected_index,
                matched_actual_index=matched_index,
                passed=True,
            )
        )

    forbidden_matches = [
        actual_index
        for actual_index, actual in enumerate(actual_states)
        if any(_matches_forbidden(matcher, actual) for matcher in case.forbidden_states)
    ]
    for actual_index in forbidden_matches:
        failures.append(
            KnowledgeStateEvaluationFailureV1(
                failure_type=KnowledgeStateEvaluationFailureType.FORBIDDEN_STATE_EMITTED,
                actual_index=actual_index,
                detail="Actual Knowledge State matches a forbidden matcher.",
            )
        )

    if case.policy.expected_unresolved_references:
        for actual_index, actual in enumerate(actual_states):
            if _has_unexpected_resolved_reference(actual):
                failures.append(
                    KnowledgeStateEvaluationFailureV1(
                        failure_type=KnowledgeStateEvaluationFailureType.UNEXPECTED_RESOLVED_REFERENCE,
                        actual_index=actual_index,
                        detail="Fixture requires unresolved references without proposal ids.",
                    )
                )

    unexpected_actual_states = sorted(unmatched_actual)
    if unexpected_actual_states and not case.policy.allow_extra_states:
        for actual_index in unexpected_actual_states:
            failures.append(
                KnowledgeStateEvaluationFailureV1(
                    failure_type=KnowledgeStateEvaluationFailureType.UNEXPECTED_EXTRA_STATE,
                    actual_index=actual_index,
                    detail="Actual Knowledge State is not expected by this strict fixture.",
                )
            )
    if case.policy.require_exact_state_count and len(case.expected_states) != len(actual_states):
        failures.append(
            KnowledgeStateEvaluationFailureV1(
                failure_type=KnowledgeStateEvaluationFailureType.STATE_COUNT_MISMATCH,
                detail="Actual state count differs from expected state count.",
            )
        )

    failure_types = list(dict.fromkeys(failure.failure_type for failure in failures))
    return KnowledgeStateEvaluationResultV1(
        case_id=case.case_id,
        passed=not failures,
        expected_state_count=len(case.expected_states),
        actual_state_count=len(actual_states),
        matched_expected_count=sum(item.passed for item in expectation_results),
        missing_expected=[item.expected_index for item in expectation_results if not item.passed],
        forbidden_matches=forbidden_matches,
        unexpected_actual_states=unexpected_actual_states,
        evidence_pass_count=evidence_pass_count,
        evidence_total_count=len(case.expected_states),
        evidence_pass_rate=(evidence_pass_count / len(case.expected_states))
        if case.expected_states
        else 1.0,
        failure_types=failure_types,
        expectation_results=expectation_results,
        failures=failures,
    )


def build_knowledge_state_evaluation_report(
    evaluations: list[KnowledgeStateEvaluationCaseBatchV1],
    cases_by_id: dict[str, KnowledgeStateEvaluationCaseV1],
    run_failures: list[KnowledgeStateEvaluationRunFailureV1] | None = None,
) -> KnowledgeStateEvaluationReportV1:
    """Aggregate already-structured case batches without Providers, persistence, or fuzzy logic."""

    run_failures = run_failures or []
    case_results: list[tuple[KnowledgeStateEvaluationCaseV1, KnowledgeStateEvaluationResultV1]] = []
    for item in evaluations:
        case = cases_by_id[item.case_id]
        case_results.append((case, evaluate_knowledge_state_case(case, item.batch)))
    failure_counts: Counter[KnowledgeStateEvaluationFailureType] = Counter()
    category_results: dict[
        KnowledgeStateEvaluationCategory, list[KnowledgeStateEvaluationResultV1]
    ] = {}
    for case, result in case_results:
        failure_counts.update(result.failure_types)
        category_results.setdefault(case.category, []).append(result)

    expected_state_count = sum(result.expected_state_count for _, result in case_results)
    actual_state_count = sum(result.actual_state_count for _, result in case_results)
    matched_expected_count = sum(result.matched_expected_count for _, result in case_results)
    evidence_pass_count = sum(result.evidence_pass_count for _, result in case_results)
    evidence_total_count = sum(result.evidence_total_count for _, result in case_results)
    status_correct_count, target_kind_correct_count = _semantic_dimension_counts(case_results)
    category_summaries = [
        KnowledgeStateEvaluationCategorySummaryV1(
            category=category,
            evaluated_case_count=len(results),
            passed_case_count=sum(result.passed for result in results),
            failed_case_count=sum(not result.passed for result in results),
            pass_rate=sum(result.passed for result in results) / len(results),
        )
        for category, results in sorted(category_results.items(), key=lambda item: str(item[0]))
    ]
    attempted_case_count = len(case_results) + len(run_failures)
    run_failure_category_counts: Counter[KnowledgeStateEvaluationRunFailureCategory] = Counter(
        failure.failure_category for failure in run_failures
    )
    is_complete = attempted_case_count == len(cases_by_id)
    return KnowledgeStateEvaluationReportV1(
        schema_version="1.1",
        attempted_case_count=attempted_case_count,
        evaluated_case_count=len(case_results),
        passed_case_count=sum(result.passed for _, result in case_results),
        failed_case_count=sum(not result.passed for _, result in case_results),
        overall_pass_rate=(sum(result.passed for _, result in case_results) / len(case_results))
        if case_results
        else 0.0,
        expected_state_count=expected_state_count,
        actual_state_count=actual_state_count,
        matched_expected_count=matched_expected_count,
        status_correct_count=status_correct_count,
        target_kind_correct_count=target_kind_correct_count,
        evidence_pass_count=evidence_pass_count,
        evidence_total_count=evidence_total_count,
        evidence_pass_rate=(evidence_pass_count / evidence_total_count)
        if evidence_total_count
        else 1.0,
        run_failed_case_count=len(run_failures),
        is_complete=is_complete,
        acceptance_eligible=(
            is_complete
            and not run_failures
            and not any(not result.passed for _, result in case_results)
        ),
        run_failure_category_counts=dict(run_failure_category_counts),
        run_failures=run_failures,
        zero_output_case_count=sum(not case.expected_states for case, _ in case_results),
        zero_output_passed_count=sum(
            not case.expected_states and result.passed for case, result in case_results
        ),
        forbidden_match_count=sum(len(result.forbidden_matches) for _, result in case_results),
        unexpected_resolved_reference_count=failure_counts[
            KnowledgeStateEvaluationFailureType.UNEXPECTED_RESOLVED_REFERENCE
        ],
        failure_type_counts=dict(failure_counts),
        category_summaries=category_summaries,
        case_results=[result for _, result in case_results],
    )


def _semantic_dimension_counts(
    case_results: list[tuple[KnowledgeStateEvaluationCaseV1, KnowledgeStateEvaluationResultV1]],
) -> tuple[int, int]:
    """Count expected states whose status or target kind was not missing or wrong."""

    status_correct_count = 0
    target_kind_correct_count = 0
    for _, result in case_results:
        for expectation in result.expectation_results:
            failures = set(expectation.failure_types)
            if (
                KnowledgeStateEvaluationFailureType.MISSING_EXPECTED_STATE not in failures
                and KnowledgeStateEvaluationFailureType.WRONG_EPISTEMIC_STATUS not in failures
            ):
                status_correct_count += 1
            if (
                KnowledgeStateEvaluationFailureType.MISSING_EXPECTED_STATE not in failures
                and KnowledgeStateEvaluationFailureType.WRONG_TARGET_KIND not in failures
            ):
                target_kind_correct_count += 1
    return status_correct_count, target_kind_correct_count


def _matches_expected(
    case: KnowledgeStateEvaluationCaseV1,
    expected: KnowledgeStateExpectationV1,
    actual: KnowledgeStateProposalV1,
) -> bool:
    subject = actual.subject
    target = actual.target
    if subject is None or target is None:
        return False
    if (
        _normalized(subject.mention_text) != _normalized(expected.subject_text)
        or subject.resolution_status != expected.subject_resolution_status
        or actual.epistemic_status != expected.epistemic_status
        or actual.epistemic_basis != expected.epistemic_basis
        or target.target_kind != expected.target_kind
        or _normalized(target.target_text) != _normalized(expected.target_text)
        or target.resolution_status != expected.target_resolution_status
        or not _matches_temporal(expected.valid_from_expectation, actual.valid_from)
        or not _matches_temporal(expected.valid_until_expectation, actual.valid_until)
    ):
        return False
    return _evidence_matches(case, expected, actual)


def _expected_failure_types(
    case: KnowledgeStateEvaluationCaseV1,
    expected: KnowledgeStateExpectationV1,
    actual_states: list[KnowledgeStateProposalV1],
) -> list[KnowledgeStateEvaluationFailureType]:
    matching_subject = [
        state
        for state in actual_states
        if state.subject
        and _normalized(state.subject.mention_text) == _normalized(expected.subject_text)
    ]
    if not matching_subject:
        return [KnowledgeStateEvaluationFailureType.MISSING_EXPECTED_STATE]
    actual = matching_subject[0]
    target = actual.target
    failure_types: list[KnowledgeStateEvaluationFailureType] = []
    if actual.epistemic_status != expected.epistemic_status:
        failure_types.append(KnowledgeStateEvaluationFailureType.WRONG_EPISTEMIC_STATUS)
    if actual.epistemic_basis != expected.epistemic_basis:
        failure_types.append(KnowledgeStateEvaluationFailureType.WRONG_EPISTEMIC_BASIS)
    if target is None or target.target_kind != expected.target_kind:
        failure_types.append(KnowledgeStateEvaluationFailureType.WRONG_TARGET_KIND)
    if target is None or _normalized(target.target_text) != _normalized(expected.target_text):
        failure_types.append(KnowledgeStateEvaluationFailureType.WRONG_TARGET_TEXT)
    if not _evidence_matches(case, expected, actual):
        failure_types.append(KnowledgeStateEvaluationFailureType.EVIDENCE_QUOTE_MISMATCH)
    if not _matches_temporal(
        expected.valid_from_expectation, actual.valid_from
    ) or not _matches_temporal(expected.valid_until_expectation, actual.valid_until):
        failure_types.append(KnowledgeStateEvaluationFailureType.TEMPORAL_ANCHOR_SHOULD_BE_NULL)
    return failure_types or [KnowledgeStateEvaluationFailureType.MISSING_EXPECTED_STATE]


def _matches_forbidden(
    matcher: KnowledgeStateStateMatcherV1,
    actual: KnowledgeStateProposalV1,
) -> bool:
    subject = actual.subject
    target = actual.target
    checks: list[bool] = []
    if matcher.subject_text is not None:
        checks.append(
            subject is not None
            and _normalized(subject.mention_text) == _normalized(matcher.subject_text)
        )
    if matcher.subject_resolution_status is not None:
        checks.append(
            subject is not None and subject.resolution_status == matcher.subject_resolution_status
        )
    if matcher.epistemic_status is not None:
        checks.append(actual.epistemic_status == matcher.epistemic_status)
    if matcher.epistemic_basis is not None:
        checks.append(actual.epistemic_basis == matcher.epistemic_basis)
    if matcher.target_kind is not None:
        checks.append(target is not None and target.target_kind == matcher.target_kind)
    if matcher.target_text is not None:
        checks.append(
            target is not None
            and _normalized(target.target_text) == _normalized(matcher.target_text)
        )
    if matcher.target_resolution_status is not None:
        checks.append(
            target is not None and target.resolution_status == matcher.target_resolution_status
        )
    if matcher.valid_from_is_null is not None:
        checks.append((actual.valid_from is None) == matcher.valid_from_is_null)
    if matcher.valid_until_is_null is not None:
        checks.append((actual.valid_until is None) == matcher.valid_until_is_null)
    return all(checks)


def _matches_temporal(
    expectation: KnowledgeTemporalAnchorExpectationV1,
    actual: KnowledgeTemporalAnchorV1 | None,
) -> bool:
    if expectation.expectation == "IGNORE":
        return True
    if expectation.expectation == "MUST_BE_NULL":
        return actual is None
    if actual is None:
        return False
    if expectation.expectation == "MUST_MATCH_UNRESOLVED_TEXT":
        return actual.resolution_status == "UNRESOLVED" and _normalized(
            actual.anchor_text or ""
        ) == _normalized(expectation.anchor_text or "")
    return (
        actual.resolution_status == "RESOLVED"
        and actual.event_proposal_id == expectation.event_proposal_id
    )


def _evidence_matches(
    case: KnowledgeStateEvaluationCaseV1,
    expected: KnowledgeStateExpectationV1,
    actual: KnowledgeStateProposalV1,
) -> bool:
    source_text_by_chunk = {chunk.chunk_id: chunk.text for chunk in case.source_chunks}
    allowed_quotes = {expected.evidence_quote, *expected.allowed_evidence_quotes}
    for evidence in actual.evidence_refs:
        source_text = source_text_by_chunk.get(evidence.chunk_id, "")
        if evidence.quote_text not in allowed_quotes or evidence.quote_text not in source_text:
            continue
        if evidence.quote_start is not None and evidence.quote_end is not None:
            if source_text[evidence.quote_start : evidence.quote_end] != evidence.quote_text:
                continue
        return True
    return False


def _has_unexpected_resolved_reference(actual: KnowledgeStateProposalV1) -> bool:
    subject = actual.subject
    target = actual.target
    return bool(
        subject
        and (subject.resolution_status != "UNRESOLVED" or subject.entity_proposal_id is not None)
        or target
        and (target.resolution_status != "UNRESOLVED" or target.proposal_id is not None)
    )


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())
