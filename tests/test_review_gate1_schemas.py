"""Review Gate 1 source/chunk quality contract tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from comic_agent.schemas import (
    ApprovedSourceChunkBundleV1,
    ReviewGate1CheckResultV1,
    ReviewGate1InputV1,
    ReviewGate1IssueV1,
    ReviewGate1ResultV1,
    ReviewGate1RunStatus,
    SourceChapterReviewItemV1,
    SourceChunkReviewItemV1,
    SourceReviewDecision,
)
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import checksum_text
from comic_agent.services.review_gate1_service import ReviewGate1Service, build_review_gate1_input

TEXT = "第一章 开始\n\n林夏站在门边。\n\n她打开了门。\n"


def _parsed():
    return DocumentParser().parse_txt("project-1", "sample.txt", TEXT)


def _policy() -> dict[str, object]:
    return {"policy_id": "gate1-policy"}


def _snapshot(parsed) -> dict[str, object]:
    normalized = TEXT.replace("\r\n", "\n").replace("\r", "\n")
    return {
        "normalized_text": normalized,
        "normalized_text_checksum": checksum_text(normalized),
        "declared_encoding": "utf-8",
        "decode_mode": "strict",
        "newline_normalization": "CRLF_TO_LF",
    }


def _input(parsed=None, **updates):
    parsed = parsed or _parsed()
    payload: dict[str, object] = {
        "project_id": parsed.document.project_id,
        "document": parsed.document,
        "source_text": _snapshot(parsed),
        "chapters": parsed.chapters,
        "chunks": parsed.chunks,
        "policy": _policy(),
        "created_at": datetime.now(UTC),
    }
    payload.update(updates)
    return payload


def _issue(
    code: str = "CHUNK_RANGE_OVERLAP",
    *,
    severity: str = "BLOCKING",
    issue_id: str = "issue-1",
    category: str = "RANGE",
    check: str = "CHUNK_RANGE",
) -> dict[str, object]:
    return {
        "issue_id": issue_id,
        "code": code,
        "category": category,
        "severity": severity,
        "check": check,
        "related_document_id": "doc-1",
        "related_chapter_input_indexes": [],
        "related_chunk_input_indexes": [0],
        "field_path": "chunks[0].char_start",
        "sanitized_message": "chunk range violates policy",
        "created_at": datetime.now(UTC),
    }


def _check(
    check: str = "CHUNK_RANGE",
    status: str = "PASSED",
    issue_ids: list[str] | None = None,
) -> dict[str, object]:
    return {"check": check, "status": status, "issue_ids": issue_ids or []}


def _chapter_review(
    chapter, status: str = "PASSED", issue_ids: list[str] | None = None
) -> dict[str, object]:
    return {
        "chapter_input_index": 0,
        "chapter_id": chapter.chapter_id,
        "chapter_order": chapter.order,
        "status": status,
        "check_results": [_check("CHAPTER_SCOPE", status, issue_ids)],
        "issue_ids": issue_ids or [],
    }


def _chunk_review(
    chunk,
    status: str = "PASSED",
    usability: str = "USABLE",
    issue_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "chunk_input_index": chunk.order,
        "chunk_id": chunk.chunk_id,
        "chunk_order": chunk.order,
        "chapter_id": chunk.chapter_id,
        "usability": usability,
        "status": status,
        "check_results": [_check("CHUNK_TEXT", status, issue_ids)],
        "issue_ids": issue_ids or [],
    }


def _result(parsed, **updates):
    issues: list[dict[str, object]] = []
    result: dict[str, object] = {
        "schema_version": "1.0",
        "review_run_id": "review-1",
        "project_id": parsed.document.project_id,
        "document_id": parsed.document.document_id,
        "document_checksum": parsed.document.checksum,
        "policy": _policy(),
        "status": "COMPLETED",
        "decision": "APPROVED",
        "document_checks": [_check("DOCUMENT_TEXT"), _check("CHUNK_RANGE")],
        "chapter_reviews": [_chapter_review(parsed.chapters[0])],
        "chunk_reviews": [_chunk_review(chunk) for chunk in parsed.chunks],
        "issues": issues,
        "approved_chunk_bundle": {
            "project_id": parsed.document.project_id,
            "document_id": parsed.document.document_id,
            "document_checksum": parsed.document.checksum,
            "review_run_id": "review-1",
            "policy_id": "gate1-policy",
            "chunk_ids": [chunk.chunk_id for chunk in parsed.chunks],
        },
        "review_method": "DETERMINISTIC",
        "reviewed_by": "review-gate-1",
        "created_at": datetime.now(UTC),
    }
    result.update(updates)
    return result


def test_parser_snapshot_can_form_approved_gate1_result() -> None:
    parsed = _parsed()
    gate_input = ReviewGate1InputV1.model_validate(_input(parsed))
    result = ReviewGate1ResultV1.model_validate(_result(parsed))

    assert gate_input.chunks
    assert result.decision == SourceReviewDecision.APPROVED
    assert result.approved_chunk_bundle is not None
    assert result.approved_chunk_bundle.chunk_ids == [chunk.chunk_id for chunk in parsed.chunks]


def test_review_gate1_policy_v11_exposes_fixed_whitespace_thresholds() -> None:
    policy = ReviewGate1InputV1.model_validate(_input()).policy

    assert policy.schema_version == "1.1"
    assert policy.max_warning_whitespace_run == 4
    assert policy.review_required_whitespace_run == 5
    with pytest.raises(ValidationError):
        type(policy).model_validate(
            policy.model_dump() | {"review_required_whitespace_run": 6}
        )


def test_review_gate1_policy_v10_remains_readable_with_legacy_whitespace_semantics() -> None:
    payload = _policy() | {"schema_version": "1.0"}
    policy = ReviewGate1InputV1.model_validate(_input(policy=payload)).policy

    assert policy.schema_version == "1.0"
    assert policy.max_warning_whitespace_run is None
    assert policy.review_required_whitespace_run is None


def test_result_without_version_and_new_fields_reads_as_legacy_v10() -> None:
    parsed = _parsed()
    payload = _result(parsed)
    payload.pop("schema_version")
    result = ReviewGate1ResultV1.model_validate(payload)
    assert result.schema_version == "1.0"
    assert result.metrics is None
    assert result.routing_advice is None


def test_gate1_input_accepts_snapshots_with_auditable_quality_anomalies() -> None:
    parsed = _parsed()
    duplicate_chunks = [parsed.chunks[0].model_copy(), parsed.chunks[0].model_copy()]
    invalid_scope = parsed.chapters[0].model_copy(update={"project_id": "other-project"})
    gate_input = ReviewGate1InputV1.model_validate(
        _input(
            parsed,
            chapters=[invalid_scope],
            chunks=duplicate_chunks,
        )
    )

    assert len(gate_input.chunks) == 2
    assert gate_input.chapters[0].project_id == "other-project"


def test_gate1_input_allows_empty_chapters_and_chunks() -> None:
    parsed = _parsed()
    gate_input = ReviewGate1InputV1.model_validate(_input(parsed, chapters=[], chunks=[]))
    assert gate_input.chapters == []
    assert gate_input.chunks == []


def test_approved_result_requires_complete_usable_chunks_and_bundle() -> None:
    parsed = _parsed()
    issue = _issue()
    invalids = (
        _result(parsed, issues=[issue]),
        _result(parsed, approved_chunk_bundle=None),
        _result(
            parsed,
            chunk_reviews=[_chunk_review(parsed.chunks[0], "FAILED", "EXCLUDED", ["issue-1"])]
            + [_chunk_review(chunk) for chunk in parsed.chunks[1:]],
        ),
        _result(
            parsed,
            approved_chunk_bundle={
                "project_id": parsed.document.project_id,
                "document_id": parsed.document.document_id,
                "document_checksum": parsed.document.checksum,
                "review_run_id": "review-1",
                "policy_id": "gate1-policy",
                "chunk_ids": [parsed.chunks[0].chunk_id] * len(parsed.chunks),
            },
        ),
    )
    for invalid in invalids:
        with pytest.raises(ValidationError):
            ReviewGate1ResultV1.model_validate(invalid)


def test_rejected_result_requires_blocking_issue_and_no_bundle() -> None:
    parsed = _parsed()
    rejected = _result(
        parsed,
        status="COMPLETED",
        decision="REJECTED",
        issues=[_issue()],
        approved_chunk_bundle=None,
        chunk_reviews=[_chunk_review(parsed.chunks[0], "FAILED", "EXCLUDED", ["issue-1"])]
        + [_chunk_review(chunk) for chunk in parsed.chunks[1:]],
    )
    assert ReviewGate1ResultV1.model_validate(rejected).decision == SourceReviewDecision.REJECTED
    for invalid in (
        rejected | {"issues": []},
        rejected | {"approved_chunk_bundle": _result(parsed)["approved_chunk_bundle"]},
    ):
        with pytest.raises(ValidationError):
            ReviewGate1ResultV1.model_validate(invalid)


def test_needs_human_review_requires_review_required_issue_and_no_bundle() -> None:
    parsed = _parsed()
    pending = _result(
        parsed,
        status="NEEDS_HUMAN_REVIEW",
        decision="NEEDS_HUMAN_REVIEW",
        issues=[
            _issue(
                "CHUNK_TEXT_EXACT_DUPLICATE",
                severity="REVIEW_REQUIRED",
                issue_id="issue-dup",
                category="DUPLICATE",
                check="CHUNK_DUPLICATE",
            )
        ],
        approved_chunk_bundle=None,
        chunk_reviews=[
            _chunk_review(
                parsed.chunks[0],
                "NEEDS_HUMAN_REVIEW",
                "NEEDS_HUMAN_REVIEW",
                ["issue-dup"],
            )
        ]
        + [_chunk_review(chunk) for chunk in parsed.chunks[1:]],
    )
    assert (
        ReviewGate1ResultV1.model_validate(pending).status
        == ReviewGate1RunStatus.NEEDS_HUMAN_REVIEW
    )
    for invalid in (
        pending | {"issues": []},
        pending | {"approved_chunk_bundle": _result(parsed)["approved_chunk_bundle"]},
        pending
        | {"issues": [_issue("GATE1_EXECUTION_FAILED", category="EXECUTION", check="CHUNK_TEXT")]},
    ):
        with pytest.raises(ValidationError):
            ReviewGate1ResultV1.model_validate(invalid)


def test_failed_result_requires_execution_blocking_issue_and_rejected_decision() -> None:
    parsed = _parsed()
    failed = _result(
        parsed,
        status="FAILED",
        decision="REJECTED",
        issues=[
            _issue(
                "GATE1_EXECUTION_FAILED",
                issue_id="exec-1",
                category="EXECUTION",
                check="CHUNK_TEXT",
            )
        ],
        approved_chunk_bundle=None,
    )
    assert ReviewGate1ResultV1.model_validate(failed).status == ReviewGate1RunStatus.FAILED
    for invalid in (
        failed | {"issues": []},
        failed | {"decision": "APPROVED"},
        failed | {"approved_chunk_bundle": _result(parsed)["approved_chunk_bundle"]},
    ):
        with pytest.raises(ValidationError):
            ReviewGate1ResultV1.model_validate(invalid)


def test_issue_and_check_cross_validation_is_strict_and_sanitized() -> None:
    with pytest.raises(ValidationError):
        ReviewGate1IssueV1.model_validate(
            _issue("CHUNK_ID_DUPLICATE", category="RANGE", check="CHUNK_RANGE")
        )
    with pytest.raises(ValidationError):
        ReviewGate1IssueV1.model_validate(_issue() | {"sanitized_message": "line1\nline2"})
    assert ReviewGate1CheckResultV1.model_validate(
        _check("CHUNK_RANGE", "PASSED", ["issue-1"])
    ).issue_ids == ["issue-1"]
    with pytest.raises(ValidationError):
        ReviewGate1CheckResultV1.model_validate(_check("CHUNK_RANGE", "FAILED"))
    with pytest.raises(ValidationError):
        ReviewGate1CheckResultV1.model_validate(_check("CHUNK_RANGE", "NEEDS_HUMAN_REVIEW"))


def test_review_items_require_unique_contiguous_input_indexes_and_valid_usability() -> None:
    parsed = _parsed()
    duplicate = _result(parsed)
    duplicate["chunk_reviews"] = [
        _chunk_review(parsed.chunks[0]),
        _chunk_review(parsed.chunks[1]) | {"chunk_input_index": 0},
    ] + [_chunk_review(chunk) for chunk in parsed.chunks[2:]]
    with pytest.raises(ValidationError):
        ReviewGate1ResultV1.model_validate(duplicate)
    with pytest.raises(ValidationError):
        SourceChunkReviewItemV1.model_validate(
            _chunk_review(parsed.chunks[0], "PASSED", "EXCLUDED")
        )
    with pytest.raises(ValidationError):
        SourceChapterReviewItemV1.model_validate(
            _chapter_review(parsed.chapters[0]) | {"chapter_input_index": -1}
        )


def test_bundle_is_id_only_and_preserves_source_order() -> None:
    parsed = _parsed()
    bundle = ApprovedSourceChunkBundleV1.model_validate(_result(parsed)["approved_chunk_bundle"])
    assert bundle.chunk_ids == [chunk.chunk_id for chunk in parsed.chunks]
    serialized = bundle.model_dump_json()
    assert "normalized_text" not in serialized
    assert "storage_uri" not in serialized
    assert "provider_response" not in serialized


def test_fresh_v11_result_requires_metrics_and_routing_advice() -> None:
    parsed = _parsed()
    review_input = build_review_gate1_input(parsed=parsed, normalized_text=TEXT)
    result = ReviewGate1Service().review(review_input)
    payload = result.model_dump()
    assert payload["schema_version"] == "1.1"
    assert payload["metrics"] is not None
    assert payload["routing_advice"] is not None

    with pytest.raises(ValidationError):
        ReviewGate1ResultV1.model_validate(payload | {"metrics": None})
    with pytest.raises(ValidationError):
        ReviewGate1ResultV1.model_validate(payload | {"routing_advice": None})


def test_v11_result_rejects_conflicting_decision_and_routing() -> None:
    parsed = _parsed()
    result = ReviewGate1Service().review(
        build_review_gate1_input(parsed=parsed, normalized_text=TEXT)
    )
    payload = result.model_dump()
    conflicting = dict(payload)
    conflicting["routing_advice"] = {
        **payload["routing_advice"],
        "action": "RECHUNK_REQUIRED",
        "retryable": True,
        "downstream_permitted": False,
    }
    with pytest.raises(ValidationError):
        ReviewGate1ResultV1.model_validate(conflicting)
