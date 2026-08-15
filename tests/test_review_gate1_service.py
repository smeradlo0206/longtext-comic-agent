"""Deterministic Review Gate 1 service tests."""

from pathlib import Path

import pytest

from comic_agent.schemas import (
    ReviewGate1InputV1,
    ReviewGate1IssueCode,
    ReviewGate1RoutingAction,
    ReviewGate1RunStatus,
    SourceReviewDecision,
)
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text
from comic_agent.services.review_gate1_service import (
    ReviewGate1Service,
    build_review_gate1_input,
)

TEXT = "第一章 开始\n\n林夏站在门边。\n\n她打开了门。\n\n第二章 转折\n\n陈野走进房间。\n"


def _parsed(text: str = TEXT):
    return DocumentParser().parse_txt("project-1", "service.txt", text)


def _input(parsed=None, text: str = TEXT, **updates) -> ReviewGate1InputV1:
    parsed = parsed or _parsed(text)
    value = build_review_gate1_input(
        parsed=parsed,
        normalized_text=text.replace("\r\n", "\n").replace("\r", "\n"),
    )
    if updates:
        value = value.model_copy(update=updates)
    return value


def test_healthy_parser_output_is_approved_and_routes_downstream() -> None:
    result = ReviewGate1Service().review(_input())

    assert result.schema_version == "1.1"
    assert result.status == ReviewGate1RunStatus.COMPLETED
    assert result.decision == SourceReviewDecision.APPROVED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER
    assert result.routing_advice.downstream_permitted is True
    assert result.approved_chunk_bundle is not None
    assert result.approved_chunk_bundle.chunk_ids == [chunk.chunk_id for chunk in _parsed().chunks]
    assert result.metrics is not None
    assert result.metrics.chunk_count == len(_parsed().chunks)
    assert result.metrics.usable_chunk_count == len(_parsed().chunks)
    assert not result.issues
    payload = result.model_dump_json()
    assert TEXT not in payload
    assert "storage_uri" not in payload
    assert "provider_response" not in payload


def test_empty_chapter_remains_human_review_gate() -> None:
    text = "第一章 空章节\n\n第二章 正文\n\n内容"
    value = _input(_parsed(text), text)

    result = ReviewGate1Service().review(value)

    assert any(
        issue.code == ReviewGate1IssueCode.CHAPTER_EMPTY
        and str(issue.severity) == "REVIEW_REQUIRED"
        for issue in result.issues
    )
    assert result.decision == SourceReviewDecision.NEEDS_HUMAN_REVIEW
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW
    assert result.approved_chunk_bundle is None


@pytest.mark.parametrize(
    ("mutator", "code", "action"),
    [
        (
            lambda value: value.model_copy(
                update={
                    "source_text": value.source_text.model_copy(
                        update={"normalized_text_checksum": "wrong"}
                    )
                }
            ),
            ReviewGate1IssueCode.DOCUMENT_CHECKSUM_MISMATCH,
            ReviewGate1RoutingAction.REIMPORT_REQUIRED,
        ),
        (
            lambda value: value.model_copy(
                update={"document": value.document.model_copy(update={"checksum": "wrong"})}
            ),
            ReviewGate1IssueCode.DOCUMENT_CHECKSUM_MISMATCH,
            ReviewGate1RoutingAction.REIMPORT_REQUIRED,
        ),
        (
            lambda value: value.model_copy(
                update={
                    "source_text": value.source_text.model_copy(
                        update={
                            "normalized_text": value.source_text.normalized_text + "\ufffd",
                            "normalized_text_checksum": checksum_text(
                                value.source_text.normalized_text + "\ufffd"
                            ),
                        }
                    ),
                    "document": value.document.model_copy(
                        update={
                            "checksum": checksum_text(value.source_text.normalized_text + "\ufffd")
                        }
                    ),
                }
            ),
            ReviewGate1IssueCode.DOCUMENT_TEXT_REPLACEMENT_CHARACTER,
            ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW,
        ),
        (
            lambda value: value.model_copy(
                update={
                    "source_text": value.source_text.model_copy(
                        update={"normalized_text": "\x00" + value.source_text.normalized_text}
                    )
                }
            ),
            ReviewGate1IssueCode.DOCUMENT_FORBIDDEN_CONTROL_CHARACTER,
            ReviewGate1RoutingAction.REIMPORT_REQUIRED,
        ),
    ],
)
def test_document_quality_issues_produce_deterministic_routing(mutator, code, action) -> None:
    value = mutator(_input())
    result = ReviewGate1Service().review(value)

    assert code in {issue.code for issue in result.issues}
    assert result.routing_advice is not None
    assert result.routing_advice.action == action


def test_excessive_whitespace_requires_human_review() -> None:
    text = "第一章 开始\n\n\n\n\n正文。\n"
    result = ReviewGate1Service().review(_input(_parsed(text), text))

    assert any(
        issue.code == ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE for issue in result.issues
    )
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW


def test_normal_import_fixture_whitespace_is_approved() -> None:
    fixture = Path("tests/fixtures/import/long_mixed_chapters.txt")
    text = fixture.read_text(encoding="utf-8")
    result = ReviewGate1Service().review(_input(_parsed(text), text))

    assert result.decision == SourceReviewDecision.APPROVED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER
    assert result.approved_chunk_bundle is not None
    assert not any(
        issue.code == ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE
        and str(issue.severity) == "REVIEW_REQUIRED"
        for issue in result.issues
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_normal_whitespace_decision_is_line_ending_invariant(newline: str) -> None:
    text = f"第一章 开始{newline}{newline}{newline}{newline}正文。{newline}"
    result = ReviewGate1Service().review(_input(_parsed(text), text))

    assert result.decision == SourceReviewDecision.APPROVED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER


@pytest.mark.parametrize(
    ("newline_count", "decision"),
    [
        (4, SourceReviewDecision.APPROVED),
        (5, SourceReviewDecision.NEEDS_HUMAN_REVIEW),
    ],
)
def test_whitespace_threshold_boundary_is_explicit(newline_count: int, decision) -> None:
    text = "第一章 开始" + ("\n" * newline_count) + "正文。\n"
    result = ReviewGate1Service().review(_input(_parsed(text), text))

    assert result.decision == decision
    issue = next(
        issue
        for issue in result.issues
        if issue.code == ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE
    )
    assert str(issue.severity) == (
        "WARNING" if newline_count == 4 else "REVIEW_REQUIRED"
    )


def test_chunk_range_overlap_requires_rechunk() -> None:
    value = _input()
    chunks = list(value.chunks)
    chunks[1] = chunks[1].model_copy(update={"char_start": chunks[0].char_start})
    value = value.model_copy(update={"chunks": chunks})
    result = ReviewGate1Service().review(value)

    assert any(issue.code == ReviewGate1IssueCode.CHUNK_RANGE_OVERLAP for issue in result.issues)
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.RECHUNK_REQUIRED
    assert result.approved_chunk_bundle is None


def test_exact_duplicate_text_is_warning_only_and_can_still_be_approved() -> None:
    value = _input()
    chunks = list(value.chunks)
    duplicate_text = chunks[0].text
    normalized = value.source_text.normalized_text + duplicate_text
    duplicate_start = len(value.source_text.normalized_text)
    chunks[1] = chunks[1].model_copy(
        update={
            "text": duplicate_text,
            "checksum": checksum_text(duplicate_text),
            "char_start": duplicate_start,
            "char_end": duplicate_start + len(duplicate_text),
        }
    )
    value = value.model_copy(
        update={
            "source_text": value.source_text.model_copy(
                update={
                    "normalized_text": normalized,
                    "normalized_text_checksum": checksum_text(normalized),
                }
            ),
            "document": value.document.model_copy(update={"checksum": checksum_text(normalized)}),
            "chunks": chunks,
        }
    )
    result = ReviewGate1Service().review(value)

    issue = next(
        issue
        for issue in result.issues
        if issue.code == ReviewGate1IssueCode.CHUNK_TEXT_EXACT_DUPLICATE
    )
    assert issue.severity == "WARNING"
    assert result.decision == SourceReviewDecision.APPROVED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER


def test_overlength_chunk_is_human_review_not_auto_truncated() -> None:
    value = _input()
    policy = value.policy.model_copy(update={"max_expected_chunk_chars": 6})
    result = ReviewGate1Service().review(value.model_copy(update={"policy": policy}))

    assert any(
        issue.code == ReviewGate1IssueCode.CHUNK_LENGTH_EXCEEDS_POLICY for issue in result.issues
    )
    assert result.decision == SourceReviewDecision.NEEDS_HUMAN_REVIEW
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW


def test_metrics_and_issue_lists_are_stable_across_repeated_runs() -> None:
    service = ReviewGate1Service()
    first = service.review(_input())
    second = service.review(_input())

    assert first.metrics == second.metrics
    assert first.routing_advice == second.routing_advice
    assert [(issue.code, issue.severity) for issue in first.issues] == [
        (issue.code, issue.severity) for issue in second.issues
    ]


def test_build_input_normalizes_newlines_and_uses_snapshot_checksum() -> None:
    parsed = _parsed(TEXT.replace("\n", "\r\n"))
    review_input = build_review_gate1_input(
        parsed=parsed, normalized_text=TEXT.replace("\n", "\r\n")
    )

    assert review_input.source_text.normalized_text == TEXT
    assert review_input.source_text.normalized_text_checksum == checksum_text(TEXT)


def test_empty_chunk_input_is_rejected_for_rechunk() -> None:
    value = _input().model_copy(update={"chapters": [], "chunks": []})
    result = ReviewGate1Service().review(value)

    assert result.decision == SourceReviewDecision.REJECTED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.RECHUNK_REQUIRED
    assert any(issue.code == ReviewGate1IssueCode.NO_USABLE_CHUNKS for issue in result.issues)


def test_unexpected_service_error_returns_sanitized_failed_result(monkeypatch) -> None:
    service = ReviewGate1Service()
    monkeypatch.setattr(
        service,
        "_document_issues",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("source text must not leak")),
    )

    result = service.review(_input())

    assert result.status == ReviewGate1RunStatus.FAILED
    assert result.decision == SourceReviewDecision.REJECTED
    assert result.routing_advice is not None
    assert result.routing_advice.action == ReviewGate1RoutingAction.STOP_REVIEW_EXECUTION_FAILED
    assert "source text must not leak" not in result.issues[0].sanitized_message
