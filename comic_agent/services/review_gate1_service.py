"""Deterministic Review Gate 1 source and chunk quality review."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from comic_agent.schemas.review import (
    ApprovedSourceChunkBundleV1,
    ReviewCheckStatus,
    ReviewGate1CategoryCountV1,
    ReviewGate1Check,
    ReviewGate1CheckResultV1,
    ReviewGate1InputV1,
    ReviewGate1IssueCategory,
    ReviewGate1IssueCode,
    ReviewGate1IssueCountV1,
    ReviewGate1IssueV1,
    ReviewGate1MetricsV1,
    ReviewGate1PolicyV1,
    ReviewGate1ResultV1,
    ReviewGate1RoutingAction,
    ReviewGate1RoutingAdviceV1,
    ReviewGate1RunStatus,
    ReviewIssueSeverity,
    SourceChapterReviewItemV1,
    SourceChunkReviewItemV1,
    SourceChunkUsability,
    SourceReviewDecision,
    SourceTextAuditSnapshotV1,
)
from comic_agent.services.document_parser import ParsedDocument
from comic_agent.services.id_service import checksum_text

_WHITESPACE_RUN_RE = re.compile(r"(?:\n[ \t]*)+")
_SEVERITY_ORDER = {
    ReviewIssueSeverity.BLOCKING: 0,
    ReviewIssueSeverity.REVIEW_REQUIRED: 1,
    ReviewIssueSeverity.WARNING: 2,
    ReviewIssueSeverity.INFO: 3,
}


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def build_review_gate1_input(
    *,
    parsed: ParsedDocument,
    normalized_text: str,
    policy: ReviewGate1PolicyV1 | None = None,
) -> ReviewGate1InputV1:
    """Build a bounded Gate 1 input using the parser's newline normalization."""

    normalized = normalized_text.replace("\r\n", "\n").replace("\r", "\n")
    snapshot = SourceTextAuditSnapshotV1(
        normalized_text=normalized,
        normalized_text_checksum=checksum_text(normalized),
    )
    return ReviewGate1InputV1(
        project_id=parsed.document.project_id,
        document=parsed.document,
        source_text=snapshot,
        chapters=parsed.chapters,
        chunks=parsed.chunks,
        policy=policy or ReviewGate1PolicyV1(policy_id="review-gate-1-v1"),
    )


@dataclass(frozen=True)
class _IssueDraft:
    code: ReviewGate1IssueCode
    severity: ReviewIssueSeverity
    chapter_indexes: tuple[int, ...] = ()
    chunk_indexes: tuple[int, ...] = ()
    field_path: str | None = None


class ReviewGate1Service:
    """Run all Gate 1 checks without mutation or external calls."""

    def review(self, review_input: ReviewGate1InputV1) -> ReviewGate1ResultV1:
        try:
            return self._review(review_input)
        except Exception as exc:
            return self._failed_result(review_input, exc)

    def _review(self, value: ReviewGate1InputV1) -> ReviewGate1ResultV1:
        normalized = value.source_text.normalized_text
        drafts: list[_IssueDraft] = []
        drafts.extend(self._document_issues(value, normalized))
        drafts.extend(self._chapter_issues(value))
        drafts.extend(self._chunk_issues(value, normalized))
        drafts = sorted(drafts, key=self._draft_sort_key)
        issues = self._materialize_issues(value, drafts)
        issue_by_id = {issue.issue_id: issue for issue in issues}

        document_checks = self._checks_for(drafts, issue_by_id, scope="document")
        chapter_reviews = self._chapter_reviews(value, drafts, issue_by_id)
        chunk_reviews = self._chunk_reviews(value, drafts, issue_by_id)
        metrics = self._metrics(
            value, normalized, issues, document_checks, chapter_reviews, chunk_reviews, drafts
        )
        routing = self._routing(issues)
        decision, status = self._decision(routing, chunk_reviews, value)
        bundle = self._bundle(value, status, decision, routing, chunk_reviews)
        return ReviewGate1ResultV1(
            schema_version="1.1",
            review_run_id=f"review-gate-1:{value.document.document_id}:{value.document.revision}",
            project_id=value.project_id,
            document_id=value.document.document_id,
            document_checksum=value.document.checksum,
            policy=value.policy,
            status=status,
            decision=decision,
            document_checks=document_checks,
            chapter_reviews=chapter_reviews,
            chunk_reviews=chunk_reviews,
            issues=issues,
            approved_chunk_bundle=bundle,
            reviewed_by="review-gate-1-deterministic",
            metrics=metrics,
            routing_advice=routing,
        )

    def _document_issues(self, value: ReviewGate1InputV1, normalized: str) -> list[_IssueDraft]:
        result: list[_IssueDraft] = []
        if not normalized.strip():
            result.append(
                _IssueDraft(ReviewGate1IssueCode.DOCUMENT_EMPTY, ReviewIssueSeverity.BLOCKING)
            )
        if (
            checksum_text(normalized) != value.source_text.normalized_text_checksum
            or value.document.checksum != value.source_text.normalized_text_checksum
        ):
            result.append(
                _IssueDraft(
                    ReviewGate1IssueCode.DOCUMENT_CHECKSUM_MISMATCH, ReviewIssueSeverity.BLOCKING
                )
            )
        if "\ufffd" in normalized:
            result.append(
                _IssueDraft(
                    ReviewGate1IssueCode.DOCUMENT_TEXT_REPLACEMENT_CHARACTER,
                    ReviewIssueSeverity.REVIEW_REQUIRED,
                )
            )
        controls = [char for char in normalized if ord(char) < 32 and char not in {"\n", "\t"}]
        if controls:
            severity = (
                ReviewIssueSeverity.BLOCKING
                if "\x00" in controls
                else ReviewIssueSeverity.REVIEW_REQUIRED
            )
            result.append(
                _IssueDraft(ReviewGate1IssueCode.DOCUMENT_FORBIDDEN_CONTROL_CHARACTER, severity)
            )
        whitespace_runs = [
            len(match.group(0).split("\n")) - 1
            for match in _WHITESPACE_RUN_RE.finditer(normalized)
        ]
        if whitespace_runs:
            warning_threshold: int | None
            review_threshold: int | None
            if value.policy.schema_version == "1.1":
                warning_threshold = value.policy.max_warning_whitespace_run
                review_threshold = value.policy.review_required_whitespace_run
            else:
                warning_threshold = None
                review_threshold = 4
            max_run = max(whitespace_runs)
            if review_threshold is not None and max_run >= review_threshold:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE,
                        ReviewIssueSeverity.REVIEW_REQUIRED,
                    )
                )
            elif warning_threshold is not None and max_run >= warning_threshold:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.DOCUMENT_EXCESSIVE_WHITESPACE,
                        ReviewIssueSeverity.WARNING,
                    )
                )
        return result

    def _chapter_issues(self, value: ReviewGate1InputV1) -> list[_IssueDraft]:
        chapters = value.chapters
        result: list[_IssueDraft] = []
        result.extend(
            self._duplicate_issue(
                ReviewGate1IssueCode.CHAPTER_ID_DUPLICATE,
                ReviewIssueSeverity.BLOCKING,
                [item.chapter_id for item in chapters],
                "chapter",
            )
        )
        result.extend(
            self._duplicate_issue(
                ReviewGate1IssueCode.CHAPTER_ORDER_DUPLICATE,
                ReviewIssueSeverity.BLOCKING,
                [item.order for item in chapters],
                "chapter",
            )
        )
        if sorted(item.order for item in chapters) != list(range(len(chapters))):
            result.append(
                _IssueDraft(
                    ReviewGate1IssueCode.CHAPTER_ORDER_NON_CONTIGUOUS, ReviewIssueSeverity.BLOCKING
                )
            )
        for index, chapter in enumerate(chapters):
            if (
                chapter.project_id != value.project_id
                or chapter.document_id != value.document.document_id
            ):
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHAPTER_SCOPE_MISMATCH,
                        ReviewIssueSeverity.BLOCKING,
                        (index,),
                        (),
                        f"chapters[{index}]",
                    )
                )
            if not chapter.title.strip():
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHAPTER_TITLE_BLANK,
                        ReviewIssueSeverity.REVIEW_REQUIRED,
                        (index,),
                        (),
                        f"chapters[{index}].title",
                    )
                )
            belonging = [
                chunk.order for chunk in value.chunks if chunk.chapter_id == chapter.chapter_id
            ]
            if not belonging:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHAPTER_EMPTY,
                        ReviewIssueSeverity.REVIEW_REQUIRED,
                        (index,),
                        (),
                        f"chapters[{index}]",
                    )
                )
            elif (min(belonging), max(belonging)) != (
                chapter.start_chunk_order,
                chapter.end_chunk_order,
            ):
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHAPTER_CHUNK_RANGE_MISMATCH,
                        ReviewIssueSeverity.BLOCKING,
                        (index,),
                        (),
                        f"chapters[{index}].start_chunk_order",
                    )
                )
        return result

    def _chunk_issues(self, value: ReviewGate1InputV1, normalized: str) -> list[_IssueDraft]:
        chunks = value.chunks
        result: list[_IssueDraft] = []
        if not chunks:
            result.append(
                _IssueDraft(
                    ReviewGate1IssueCode.NO_USABLE_CHUNKS,
                    ReviewIssueSeverity.BLOCKING,
                )
            )
        result.extend(
            self._duplicate_issue(
                ReviewGate1IssueCode.CHUNK_ID_DUPLICATE,
                ReviewIssueSeverity.BLOCKING,
                [item.chunk_id for item in chunks],
                "chunk",
            )
        )
        result.extend(
            self._duplicate_issue(
                ReviewGate1IssueCode.CHUNK_ORDER_DUPLICATE,
                ReviewIssueSeverity.BLOCKING,
                [item.order for item in chunks],
                "chunk",
            )
        )
        if sorted(item.order for item in chunks) != list(range(len(chunks))):
            result.append(
                _IssueDraft(
                    ReviewGate1IssueCode.CHUNK_ORDER_NON_CONTIGUOUS, ReviewIssueSeverity.BLOCKING
                )
            )
        chapter_ids = {chapter.chapter_id for chapter in value.chapters}
        ranges: list[tuple[int, int, int]] = []
        for index, chunk in enumerate(chunks):
            if (
                chunk.project_id != value.project_id
                or chunk.document_id != value.document.document_id
            ):
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_SCOPE_MISMATCH,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        (index,),
                        f"chunks[{index}]",
                    )
                )
            if chunk.chapter_id not in chapter_ids:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_CHAPTER_NOT_FOUND,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        (index,),
                        f"chunks[{index}].chapter_id",
                    )
                )
            if not chunk.text.strip():
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_TEXT_WHITESPACE_ONLY,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        (index,),
                        f"chunks[{index}].text",
                    )
                )
            if checksum_text(chunk.text) != chunk.checksum:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_CHECKSUM_MISMATCH,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        (index,),
                        f"chunks[{index}].checksum",
                    )
                )
            if chunk.char_start is None or chunk.char_end is None:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_OFFSETS_MISSING,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        (index,),
                        f"chunks[{index}].char_start",
                    )
                )
            else:
                if (
                    chunk.char_start < 0
                    or chunk.char_end <= chunk.char_start
                    or chunk.char_end > len(normalized)
                ):
                    result.append(
                        _IssueDraft(
                            ReviewGate1IssueCode.CHUNK_OFFSET_OUT_OF_BOUNDS,
                            ReviewIssueSeverity.BLOCKING,
                            (),
                            (index,),
                            f"chunks[{index}].char_end",
                        )
                    )
                else:
                    ranges.append((index, chunk.char_start, chunk.char_end))
                    if normalized[chunk.char_start : chunk.char_end] != chunk.text:
                        result.append(
                            _IssueDraft(
                                ReviewGate1IssueCode.CHUNK_TEXT_RANGE_MISMATCH,
                                ReviewIssueSeverity.BLOCKING,
                                (),
                                (index,),
                                f"chunks[{index}].text",
                            )
                        )
            if len(chunk.text) > value.policy.max_expected_chunk_chars:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_LENGTH_EXCEEDS_POLICY,
                        ReviewIssueSeverity.REVIEW_REQUIRED,
                        (),
                        (index,),
                        f"chunks[{index}].text",
                    )
                )
        range_groups = defaultdict(list)
        for index, start, end in ranges:
            range_groups[(start, end)].append(index)
        for indexes in range_groups.values():
            if len(indexes) > 1:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_RANGE_DUPLICATE,
                        ReviewIssueSeverity.BLOCKING,
                        (),
                        tuple(indexes),
                        "chunks[*].char_start",
                    )
                )
        for position, (left_index, left_start, left_end) in enumerate(ranges):
            for right_index, right_start, right_end in ranges[position + 1 :]:
                if left_start < right_end and right_start < left_end:
                    result.append(
                        _IssueDraft(
                            ReviewGate1IssueCode.CHUNK_RANGE_OVERLAP,
                            ReviewIssueSeverity.BLOCKING,
                            (),
                            (left_index, right_index),
                            "chunks[*].char_start",
                        )
                    )
        text_groups = defaultdict(list)
        for index, chunk in enumerate(chunks):
            text_groups[chunk.text].append(index)
        for indexes in text_groups.values():
            ranges_for_text = {
                (chunks[index].char_start, chunks[index].char_end) for index in indexes
            }
            if len(indexes) > 1 and len(ranges_for_text) > 1:
                result.append(
                    _IssueDraft(
                        ReviewGate1IssueCode.CHUNK_TEXT_EXACT_DUPLICATE,
                        ReviewIssueSeverity.WARNING,
                        (),
                        tuple(indexes),
                        "chunks[*].text",
                    )
                )
        return result

    def _duplicate_issue(
        self,
        code: ReviewGate1IssueCode,
        severity: ReviewIssueSeverity,
        values: list[Any],
        kind: str,
    ) -> list[_IssueDraft]:
        groups = defaultdict(list)
        for index, item in enumerate(values):
            groups[item].append(index)
        return [
            _IssueDraft(
                code,
                severity,
                tuple(indexes) if kind == "chapter" else (),
                tuple(indexes) if kind == "chunk" else (),
            )
            for indexes in groups.values()
            if len(indexes) > 1
        ]

    def _draft_sort_key(self, draft: _IssueDraft) -> tuple[int, str, tuple[int, ...], str]:
        indexes = draft.chapter_indexes or draft.chunk_indexes or (10**9,)
        return (_SEVERITY_ORDER[draft.severity], draft.code.value, indexes, draft.field_path or "")

    def _materialize_issues(
        self, value: ReviewGate1InputV1, drafts: list[_IssueDraft]
    ) -> list[ReviewGate1IssueV1]:
        issues = []
        for counter, draft in enumerate(drafts, 1):
            category, check = self._rule(draft.code)
            message = self._message(draft.code)
            issues.append(
                ReviewGate1IssueV1(
                    issue_id=f"gate1-issue-{counter:04d}",
                    code=draft.code,
                    category=category,
                    severity=draft.severity,
                    check=check,
                    related_document_id=value.document.document_id,
                    related_chapter_input_indexes=list(draft.chapter_indexes),
                    related_chunk_input_indexes=list(draft.chunk_indexes),
                    field_path=draft.field_path,
                    sanitized_message=message,
                )
            )
        return issues

    def _rule(
        self, code: ReviewGate1IssueCode
    ) -> tuple[ReviewGate1IssueCategory, ReviewGate1Check]:
        from comic_agent.schemas.review import _GATE1_CODE_RULES

        return _GATE1_CODE_RULES[code]

    def _message(self, code: ReviewGate1IssueCode) -> str:
        return f"deterministic Gate 1 check reported {code.value}"

    def _checks_for(
        self,
        drafts: list[_IssueDraft],
        issue_by_id: dict[str, ReviewGate1IssueV1],
        scope: str,
    ) -> list[ReviewGate1CheckResultV1]:
        checks = defaultdict(list)
        for issue in issue_by_id.values():
            if (
                scope == "document"
                and issue.related_chapter_input_indexes == []
                and issue.related_chunk_input_indexes == []
            ):
                checks[issue.check].append(issue.issue_id)
        return [
            ReviewGate1CheckResultV1(
                check=check,
                status=self._check_status(ids, issue_by_id),
                issue_ids=ids,
            )
            for check, ids in sorted(checks.items(), key=lambda item: _enum_value(item[0]))
        ]

    def _check_status(
        self, issue_ids: list[str], issue_by_id: dict[str, ReviewGate1IssueV1]
    ) -> ReviewCheckStatus:
        severities = {issue_by_id[item].severity for item in issue_ids}
        if ReviewIssueSeverity.BLOCKING in severities:
            return ReviewCheckStatus.FAILED
        if ReviewIssueSeverity.REVIEW_REQUIRED in severities:
            return ReviewCheckStatus.NEEDS_HUMAN_REVIEW
        return ReviewCheckStatus.PASSED

    def _chapter_reviews(
        self,
        value: ReviewGate1InputV1,
        drafts: list[_IssueDraft],
        issue_by_id: dict[str, ReviewGate1IssueV1],
    ) -> list[SourceChapterReviewItemV1]:
        result = []
        for index, chapter in enumerate(value.chapters):
            ids = [
                issue.issue_id
                for issue in issue_by_id.values()
                if index in issue.related_chapter_input_indexes
            ]
            checks = self._checks_for_related(ids, issue_by_id)
            status = self._check_status(ids, issue_by_id) if ids else ReviewCheckStatus.PASSED
            result.append(
                SourceChapterReviewItemV1(
                    chapter_input_index=index,
                    chapter_id=chapter.chapter_id,
                    chapter_order=chapter.order,
                    status=status,
                    check_results=checks,
                    issue_ids=ids,
                )
            )
        return result

    def _chunk_reviews(
        self,
        value: ReviewGate1InputV1,
        drafts: list[_IssueDraft],
        issue_by_id: dict[str, ReviewGate1IssueV1],
    ) -> list[SourceChunkReviewItemV1]:
        global_blocking = any(
            issue.severity == ReviewIssueSeverity.BLOCKING for issue in issue_by_id.values()
        )
        global_review = any(
            issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED for issue in issue_by_id.values()
        )
        result = []
        for index, chunk in enumerate(value.chunks):
            ids = [
                issue.issue_id
                for issue in issue_by_id.values()
                if index in issue.related_chunk_input_indexes
            ]
            if global_blocking and not ids:
                ids = [
                    issue.issue_id
                    for issue in issue_by_id.values()
                    if issue.severity == ReviewIssueSeverity.BLOCKING
                ]
            if ids:
                status = self._check_status(ids, issue_by_id)
            elif global_review:
                status = ReviewCheckStatus.NEEDS_HUMAN_REVIEW
            else:
                status = ReviewCheckStatus.PASSED
            usability = (
                SourceChunkUsability.EXCLUDED
                if status == ReviewCheckStatus.FAILED
                else SourceChunkUsability.NEEDS_HUMAN_REVIEW
                if status == ReviewCheckStatus.NEEDS_HUMAN_REVIEW
                else SourceChunkUsability.USABLE
            )
            result.append(
                SourceChunkReviewItemV1(
                    chunk_input_index=index,
                    chunk_id=chunk.chunk_id,
                    chunk_order=chunk.order,
                    chapter_id=chunk.chapter_id,
                    usability=usability,
                    status=status,
                    check_results=self._checks_for_related(ids, issue_by_id),
                    issue_ids=ids,
                )
            )
        return result

    def _checks_for_related(
        self, ids: list[str], issue_by_id: dict[str, ReviewGate1IssueV1]
    ) -> list[ReviewGate1CheckResultV1]:
        grouped = defaultdict(list)
        for issue_id in ids:
            grouped[issue_by_id[issue_id].check].append(issue_id)
        return [
            ReviewGate1CheckResultV1(
                check=check,
                status=self._check_status(issue_ids, issue_by_id),
                issue_ids=issue_ids,
            )
            for check, issue_ids in sorted(grouped.items(), key=lambda item: _enum_value(item[0]))
        ]

    def _metrics(
        self,
        value: ReviewGate1InputV1,
        normalized: str,
        issues: list[ReviewGate1IssueV1],
        document_checks: list[ReviewGate1CheckResultV1],
        chapter_reviews: list[SourceChapterReviewItemV1],
        chunk_reviews: list[SourceChunkReviewItemV1],
        drafts: list[_IssueDraft],
    ) -> ReviewGate1MetricsV1:
        chunks = value.chunks
        complete = sum(
            chunk.char_start is not None and chunk.char_end is not None for chunk in chunks
        )
        valid = sum(
            chunk.char_start is not None
            and chunk.char_end is not None
            and 0 <= chunk.char_start < chunk.char_end <= len(normalized)
            and normalized[chunk.char_start : chunk.char_end] == chunk.text
            for chunk in chunks
        )
        check_results = [
            *document_checks,
            *(check for item in chapter_reviews for check in item.check_results),
            *(check for item in chunk_reviews for check in item.check_results),
        ]
        code_counts = Counter(issue.code for issue in issues)
        category_counts = Counter(issue.category for issue in issues)
        text_groups = defaultdict(list)
        for chunk in chunks:
            text_groups[chunk.text].append((chunk.char_start, chunk.char_end))
        exact_duplicate_text_groups = sum(
            len(set(group)) > 1 for group in text_groups.values() if len(group) > 1
        )
        overlapping_pairs = sum(
            1 for draft in drafts if draft.code == ReviewGate1IssueCode.CHUNK_RANGE_OVERLAP
        )
        duplicate_range_pairs = sum(
            len(draft.chunk_indexes) * (len(draft.chunk_indexes) - 1) // 2
            for draft in drafts
            if draft.code == ReviewGate1IssueCode.CHUNK_RANGE_DUPLICATE
        )
        return ReviewGate1MetricsV1(
            normalized_text_char_count=len(normalized),
            chapter_count=len(value.chapters),
            chunk_count=len(chunks),
            total_chunk_char_count=sum(len(chunk.text) for chunk in chunks),
            max_chunk_char_count=max((len(chunk.text) for chunk in chunks), default=0),
            chunks_with_complete_offsets=complete,
            chunks_missing_offsets=len(chunks) - complete,
            chunks_with_valid_text_range=valid,
            chunks_with_invalid_text_range=len(chunks) - valid,
            usable_chunk_count=sum(
                item.usability == SourceChunkUsability.USABLE for item in chunk_reviews
            ),
            excluded_chunk_count=sum(
                item.usability == SourceChunkUsability.EXCLUDED for item in chunk_reviews
            ),
            needs_human_review_chunk_count=sum(
                item.usability == SourceChunkUsability.NEEDS_HUMAN_REVIEW for item in chunk_reviews
            ),
            checks_passed_count=sum(
                check.status == ReviewCheckStatus.PASSED for check in check_results
            ),
            checks_failed_count=sum(
                check.status == ReviewCheckStatus.FAILED for check in check_results
            ),
            checks_needs_human_review_count=sum(
                check.status == ReviewCheckStatus.NEEDS_HUMAN_REVIEW for check in check_results
            ),
            checks_not_applicable_count=sum(
                check.status == ReviewCheckStatus.NOT_APPLICABLE for check in check_results
            ),
            blocking_issue_count=sum(
                issue.severity == ReviewIssueSeverity.BLOCKING for issue in issues
            ),
            review_required_issue_count=sum(
                issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED for issue in issues
            ),
            warning_issue_count=sum(
                issue.severity == ReviewIssueSeverity.WARNING for issue in issues
            ),
            info_issue_count=sum(issue.severity == ReviewIssueSeverity.INFO for issue in issues),
            duplicate_chunk_id_group_count=self._group_count([chunk.chunk_id for chunk in chunks]),
            duplicate_chunk_order_group_count=self._group_count([chunk.order for chunk in chunks]),
            overlapping_range_pair_count=overlapping_pairs,
            duplicate_range_pair_count=duplicate_range_pairs,
            exact_duplicate_text_group_count=exact_duplicate_text_groups,
            issue_counts_by_code=[
                ReviewGate1IssueCountV1(code=code, count=count)
                for code, count in sorted(
                    code_counts.items(), key=lambda item: _enum_value(item[0])
                )
            ],
            issue_counts_by_category=[
                ReviewGate1CategoryCountV1(category=category, count=count)
                for category, count in sorted(
                    category_counts.items(), key=lambda item: _enum_value(item[0])
                )
            ],
        )

    def _group_count(self, values: list[Any]) -> int:
        return sum(count > 1 for count in Counter(values).values())

    def _routing(self, issues: list[ReviewGate1IssueV1]) -> ReviewGate1RoutingAdviceV1:
        codes = {issue.code for issue in issues}
        blocking = sorted(
            {issue.code for issue in issues if issue.severity == ReviewIssueSeverity.BLOCKING},
            key=_enum_value,
        )
        review_required = sorted(
            {
                issue.code
                for issue in issues
                if issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED
            },
            key=_enum_value,
        )
        warning = sorted(
            {issue.code for issue in issues if issue.severity == ReviewIssueSeverity.WARNING},
            key=_enum_value,
        )
        reasons = sorted(codes, key=_enum_value)
        if ReviewGate1IssueCode.GATE1_EXECUTION_FAILED in codes:
            action = ReviewGate1RoutingAction.STOP_REVIEW_EXECUTION_FAILED
        elif blocking:
            reimport_codes = {
                ReviewGate1IssueCode.DOCUMENT_EMPTY,
                ReviewGate1IssueCode.DOCUMENT_CHECKSUM_MISMATCH,
                ReviewGate1IssueCode.DOCUMENT_TEXT_REPLACEMENT_CHARACTER,
                ReviewGate1IssueCode.DOCUMENT_FORBIDDEN_CONTROL_CHARACTER,
            }
            action = (
                ReviewGate1RoutingAction.REIMPORT_REQUIRED
                if set(blocking) & reimport_codes
                else ReviewGate1RoutingAction.RECHUNK_REQUIRED
            )
        elif review_required:
            action = ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW
        else:
            action = ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER
        return ReviewGate1RoutingAdviceV1(
            action=action,
            reason_codes=reasons,
            blocking_issue_codes=blocking,
            review_required_issue_codes=review_required,
            warning_issue_codes=warning,
            retryable=action
            in {
                ReviewGate1RoutingAction.REIMPORT_REQUIRED,
                ReviewGate1RoutingAction.RECHUNK_REQUIRED,
            },
            requires_human_review=action == ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW,
            downstream_permitted=action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER,
        )

    def _decision(
        self,
        routing: ReviewGate1RoutingAdviceV1,
        chunk_reviews: list[SourceChunkReviewItemV1],
        value: ReviewGate1InputV1,
    ) -> tuple[SourceReviewDecision, ReviewGate1RunStatus]:
        if routing.action == ReviewGate1RoutingAction.CONTINUE_TO_CONTEXT_BUILDER and chunk_reviews:
            return SourceReviewDecision.APPROVED, ReviewGate1RunStatus.COMPLETED
        if routing.action == ReviewGate1RoutingAction.HOLD_FOR_HUMAN_REVIEW:
            return SourceReviewDecision.NEEDS_HUMAN_REVIEW, ReviewGate1RunStatus.NEEDS_HUMAN_REVIEW
        return (
            SourceReviewDecision.REJECTED,
            ReviewGate1RunStatus.FAILED
            if routing.action == ReviewGate1RoutingAction.STOP_REVIEW_EXECUTION_FAILED
            else ReviewGate1RunStatus.COMPLETED,
        )

    def _bundle(
        self,
        value: ReviewGate1InputV1,
        status: ReviewGate1RunStatus,
        decision: SourceReviewDecision,
        routing: ReviewGate1RoutingAdviceV1,
        chunk_reviews: list[SourceChunkReviewItemV1],
    ) -> ApprovedSourceChunkBundleV1 | None:
        if decision != SourceReviewDecision.APPROVED or status != ReviewGate1RunStatus.COMPLETED:
            return None
        return ApprovedSourceChunkBundleV1(
            project_id=value.project_id,
            document_id=value.document.document_id,
            document_checksum=value.document.checksum,
            review_run_id=f"review-gate-1:{value.document.document_id}:{value.document.revision}",
            policy_id=value.policy.policy_id,
            chunk_ids=[
                item.chunk_id for item in sorted(chunk_reviews, key=lambda item: item.chunk_order)
            ],
        )

    def _failed_result(
        self, value: ReviewGate1InputV1, exc: Exception
    ) -> ReviewGate1ResultV1:
        chunk_indexes = list(range(len(value.chunks)))
        issue = ReviewGate1IssueV1(
            issue_id="gate1-issue-0001",
            code=ReviewGate1IssueCode.GATE1_EXECUTION_FAILED,
            category=ReviewGate1IssueCategory.EXECUTION,
            severity=ReviewIssueSeverity.BLOCKING,
            check=ReviewGate1Check.CHUNK_TEXT,
            related_document_id=value.document.document_id,
            related_chunk_input_indexes=chunk_indexes,
            sanitized_message=f"deterministic review failed with {type(exc).__name__}",
        )
        document_checks = [
            ReviewGate1CheckResultV1(
                check=ReviewGate1Check.CHUNK_TEXT,
                status=ReviewCheckStatus.FAILED,
                issue_ids=[issue.issue_id],
            )
        ]
        chapter_reviews = [
            SourceChapterReviewItemV1(
                chapter_input_index=index,
                chapter_id=chapter.chapter_id,
                chapter_order=chapter.order,
                status=ReviewCheckStatus.PASSED,
            )
            for index, chapter in enumerate(value.chapters)
        ]
        chunk_reviews = [
            SourceChunkReviewItemV1(
                chunk_input_index=index,
                chunk_id=chunk.chunk_id,
                chunk_order=chunk.order,
                chapter_id=chunk.chapter_id,
                usability=SourceChunkUsability.EXCLUDED,
                status=ReviewCheckStatus.FAILED,
                check_results=[
                    ReviewGate1CheckResultV1(
                        check=ReviewGate1Check.CHUNK_TEXT,
                        status=ReviewCheckStatus.FAILED,
                        issue_ids=[issue.issue_id],
                    )
                ],
                issue_ids=[issue.issue_id],
            )
            for index, chunk in enumerate(value.chunks)
        ]
        check_failed_count = 1 + len(chunk_reviews)
        metrics = ReviewGate1MetricsV1(
            normalized_text_char_count=len(value.source_text.normalized_text),
            chapter_count=len(value.chapters),
            chunk_count=len(value.chunks),
            total_chunk_char_count=sum(len(chunk.text) for chunk in value.chunks),
            max_chunk_char_count=max((len(chunk.text) for chunk in value.chunks), default=0),
            chunks_with_complete_offsets=0,
            chunks_missing_offsets=len(value.chunks),
            chunks_with_valid_text_range=0,
            chunks_with_invalid_text_range=len(value.chunks),
            usable_chunk_count=0,
            excluded_chunk_count=len(value.chunks),
            needs_human_review_chunk_count=0,
            checks_passed_count=0,
            checks_failed_count=1,
            checks_needs_human_review_count=0,
            checks_not_applicable_count=0,
            blocking_issue_count=1,
            review_required_issue_count=0,
            warning_issue_count=0,
            info_issue_count=0,
            duplicate_chunk_id_group_count=0,
            duplicate_chunk_order_group_count=0,
            overlapping_range_pair_count=0,
            duplicate_range_pair_count=0,
            exact_duplicate_text_group_count=0,
            issue_counts_by_code=[ReviewGate1IssueCountV1(code=issue.code, count=1)],
            issue_counts_by_category=[ReviewGate1CategoryCountV1(category=issue.category, count=1)],
        )
        metrics = metrics.model_copy(update={"checks_failed_count": check_failed_count})
        routing = ReviewGate1RoutingAdviceV1(
            action=ReviewGate1RoutingAction.STOP_REVIEW_EXECUTION_FAILED,
            reason_codes=[issue.code],
            blocking_issue_codes=[issue.code],
            retryable=False,
            requires_human_review=False,
            downstream_permitted=False,
        )
        return ReviewGate1ResultV1(
            schema_version="1.1",
            review_run_id="review-gate-1-failed",
            project_id=value.project_id,
            document_id=value.document.document_id,
            document_checksum=value.document.checksum,
            policy=value.policy,
            status=ReviewGate1RunStatus.FAILED,
            decision=SourceReviewDecision.REJECTED,
            document_checks=document_checks,
            chapter_reviews=chapter_reviews,
            chunk_reviews=chunk_reviews,
            issues=[issue],
            approved_chunk_bundle=None,
            reviewed_by="review-gate-1-deterministic",
            metrics=metrics,
            routing_advice=routing,
        )
