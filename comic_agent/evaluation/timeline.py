"""Gold-set loading and metrics for the production TimelineAgent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pydantic import Field, model_validator

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.schemas.base import StrictBaseModel
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EventProposalV1,
    StateChangeProposalV1,
    TemporalRelation,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import TimelineAnalysisInputV1, TimelineAnalysisMode
from comic_agent.services.commit_service import CommitService

EVAL_RELATIONS = {
    TemporalRelation.BEFORE,
    TemporalRelation.AFTER,
    TemporalRelation.SIMULTANEOUS,
    TemporalRelation.OVERLAPS,
    TemporalRelation.UNKNOWN,
}


class TimelineGoldAnnotationV1(StrictBaseModel):
    reason: str = Field(min_length=1)
    difficulty: str | None = None
    notes: str | None = None


class TimelineGoldCaseV1(StrictBaseModel):
    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    source_chunks: list[SourceChunkV1] = Field(min_length=2)
    event_a: EventProposalV1
    event_b: EventProposalV1
    claim_proposals: list[ClaimProposalV1] = Field(default_factory=list)
    state_change_proposals: list[StateChangeProposalV1] = Field(default_factory=list)
    gold_relation: TemporalRelation
    gold_conflict: bool
    gold_duplicate: bool
    annotation: TimelineGoldAnnotationV1

    @model_validator(mode="after")
    def validate_case(self) -> TimelineGoldCaseV1:
        if self.gold_relation not in EVAL_RELATIONS:
            raise ValueError("gold_relation is not supported by Timeline V2")
        chunks = {chunk.chunk_id for chunk in self.source_chunks}
        evidence_groups = [self.event_a.evidence_refs, self.event_b.evidence_refs]
        evidence_groups.extend(proposal.evidence_refs for proposal in self.claim_proposals)
        evidence_groups.extend(proposal.evidence_refs for proposal in self.state_change_proposals)
        if any(ref.chunk_id not in chunks for group in evidence_groups for ref in group):
            raise ValueError("proposal evidence must reference a case source chunk")
        return self


class _CaseLookup:
    def __init__(self, chunks: list[SourceChunkV1]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        return self._chunks.get(chunk_id)


@dataclass(frozen=True)
class TimelineEvaluationResult:
    case_id: str
    category: str
    mode: str
    gold_relation: str
    predicted_relation: str | None
    relation_correct: bool | None
    gold_conflict: bool
    predicted_conflict: bool | None
    gold_duplicate: bool
    predicted_duplicate: bool | None
    evidence_validation: bool | None
    latency_ms: float
    status: str
    error_type: str | None = None
    error_message: str | None = None
    failure_category: str | None = None


def load_timeline_gold_cases(path: Path) -> list[TimelineGoldCaseV1]:
    cases: list[TimelineGoldCaseV1] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = TimelineGoldCaseV1.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"invalid gold case at line {line_number}: {exc}") from exc
        if case.case_id in seen:
            raise ValueError(f"duplicate gold case_id: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    return cases


def evaluate_case(
    case: TimelineGoldCaseV1, agent: TimelineAgent, mode: TimelineAnalysisMode
) -> TimelineEvaluationResult:
    started = perf_counter()
    stage = "input_evidence"
    try:
        validator = CommitService(_CaseLookup(case.source_chunks))
        validator.validate_story_proposal_evidence(case.event_a)
        validator.validate_story_proposal_evidence(case.event_b)
        stage = "agent_execution"
        proposal = agent.run(
            TimelineAnalysisInputV1(
                project_id="timeline-gold",
                mode=mode,
                event_proposals=[case.event_a, case.event_b],
                claim_proposals=case.claim_proposals,
                state_change_proposals=case.state_change_proposals,
            ),
            source_chunks=case.source_chunks,
        )
        stage = "output_evidence"
        for relation in proposal.temporal_relations:
            validator.validate_temporal_relation_evidence(relation, "timeline-gold")
        predicted_relation = (
            proposal.temporal_relations[0].relation if proposal.temporal_relations else None
        )
        return TimelineEvaluationResult(
            case.case_id,
            case.category,
            str(mode),
            str(case.gold_relation),
            str(predicted_relation) if predicted_relation else None,
            str(predicted_relation) == str(case.gold_relation),
            case.gold_conflict,
            bool(proposal.conflicts),
            case.gold_duplicate,
            bool(proposal.duplicate_candidates),
            True,
            (perf_counter() - started) * 1000,
            "succeeded",
        )
    except Exception as exc:
        # Evaluation must record provider/network/schema failures per case instead of
        # aborting the batch or misclassifying an execution failure as UNKNOWN.
        category = classify_failure(exc, stage)
        return TimelineEvaluationResult(
            case.case_id,
            case.category,
            str(mode),
            str(case.gold_relation),
            None,
            None,
            case.gold_conflict,
            None,
            case.gold_duplicate,
            None,
            False
            if category in {"input_evidence", "evidence_selection", "output_evidence"}
            else None,
            (perf_counter() - started) * 1000,
            "failed",
            type(exc).__name__,
            str(exc),
            category,
        )


def classify_failure(exc: Exception, stage: str) -> str:
    """Return a stable evaluation failure family without changing production behavior."""

    if stage == "input_evidence":
        return "input_evidence"
    if stage == "output_evidence":
        return "output_evidence"
    if isinstance(exc, (ConnectionError, TimeoutError)) or type(exc).__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
    }:
        return "network"
    if isinstance(exc, ValueError) and "unknown evidence id" in str(exc):
        return "evidence_selection"
    return "provider_or_schema"


def result_to_json(result: TimelineEvaluationResult) -> dict[str, object]:
    return result.__dict__.copy()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def calculate_metrics(results: list[TimelineEvaluationResult], mode: str) -> dict[str, object]:
    successful = [result for result in results if result.status == "succeeded"]
    labels = [relation.value for relation in sorted(EVAL_RELATIONS, key=str)]
    confusion = {gold: {predicted: 0 for predicted in labels} for gold in labels}
    for result in successful:
        if result.predicted_relation is not None:
            confusion[result.gold_relation][result.predicted_relation] += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    def binary(field: str) -> dict[str, int | float | None]:
        pairs = [
            (getattr(result, field), getattr(result, f"gold_{field[10:]}")) for result in successful
        ]
        tp = sum(predicted is True and gold is True for predicted, gold in pairs)
        fp = sum(predicted is True and gold is False for predicted, gold in pairs)
        tn = sum(predicted is False and gold is False for predicted, gold in pairs)
        fn = sum(predicted is False and gold is True for predicted, gold in pairs)
        return {
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
        }

    gold_unknown = [result for result in successful if result.gold_relation == "UNKNOWN"]
    predicted_unknown = [result for result in successful if result.predicted_relation == "UNKNOWN"]
    correct = sum(result.relation_correct is True for result in successful)
    failures_by_category: dict[str, int] = {}
    for result in results:
        if result.status == "failed":
            category = result.failure_category or "unclassified"
            failures_by_category[category] = failures_by_category.get(category, 0) + 1
    return {
        "mode": mode,
        "total_cases": len(results),
        "attempted_cases": len(results),
        "successful_cases": len(successful),
        "failed_cases": len(results) - len(successful),
        "execution_success_rate": ratio(len(successful), len(results)),
        "failures_by_category": failures_by_category,
        "relation": {
            "accuracy": ratio(correct, len(successful)),
            "successful_case_accuracy": ratio(correct, len(successful)),
            "attempted_case_accuracy": ratio(correct, len(results)),
            "per_class_accuracy": {
                label: ratio(
                    sum(
                        result.relation_correct is True
                        for result in successful
                        if result.gold_relation == label
                    ),
                    sum(result.gold_relation == label for result in successful),
                )
                for label in labels
            },
            "unknown_precision": ratio(
                sum(result.gold_relation == "UNKNOWN" for result in predicted_unknown),
                len(predicted_unknown),
            ),
            "unknown_recall": ratio(
                sum(result.predicted_relation == "UNKNOWN" for result in gold_unknown),
                len(gold_unknown),
            ),
            "unsupported_temporal_assertion_rate": ratio(
                sum(result.predicted_relation != "UNKNOWN" for result in gold_unknown),
                len(gold_unknown),
            ),
            "confusion_matrix": confusion,
        },
        "conflict": binary("predicted_conflict"),
        "duplicate": binary("predicted_duplicate"),
        "evidence": {
            "validation_failures": sum(result.evidence_validation is False for result in results),
            "not_evaluated": sum(result.evidence_validation is None for result in results),
        },
    }
