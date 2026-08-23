"""Automatic, bounded handoff from a completed Narrative Analyst run to Gate 2."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas import (
    EvidenceRefV1,
    NarrativeAnalysisReviewRouteV1,
    NarrativeAnalysisRunStatus,
    NarrativeExecutionBundleV1,
    NarrativeExecutionExcludedItemV1,
    NarrativeExecutionFailedWindowV1,
    NarrativeExecutionProvenanceV1,
    NarrativeExecutionStatus,
    ProposalRecoveryDiagnosticV1,
    ProposalReviewDecision,
    ProposalReviewDecisionV1,
    ReviewableProposalEnvelopeV1,
    ReviewCheckStatus,
    ReviewGate2InputV1,
    ReviewGate2ResultV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
    ReviewIssueV1,
)
from comic_agent.schemas.workflow import (
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.id_service import stable_id
from comic_agent.services.review_gate2_service import (
    ReviewGate2Service,
    ReviewGate2ServiceContext,
    build_review_gate2_input,
)

_NON_RETRYABLE_DIAGNOSTIC_CODES = {
    ReviewIssueCode.EXACT_DUPLICATE,
    ReviewIssueCode.ANALYSIS_RUN_MISMATCH,
    ReviewIssueCode.AGENT_RUN_NOT_FOUND,
    ReviewIssueCode.PROVENANCE_MISSING,
    ReviewIssueCode.MODE_SCHEMA_MISMATCH,
    ReviewIssueCode.PROPOSAL_SCHEMA_MISMATCH,
    ReviewIssueCode.UNSUPPORTED_PROPOSAL_SCHEMA,
}


class NarrativeGate2HandoffCoordinator:
    """Claim and complete the deterministic, resumable Gate 2 handoff exactly once."""

    def __init__(
        self,
        *,
        source_repository: SourceRepository,
        analysis_repository: NarrativeAnalysisRepository,
        review_service: ReviewGate2Service | None = None,
    ) -> None:
        self._source_repository = source_repository
        self._analysis_repository = analysis_repository
        self._review_service = review_service or ReviewGate2Service()

    def review_if_ready(self, analysis_run_id: str) -> NarrativeAnalysisRunV1:
        """Persist a deterministic Gate 2 audit only after aggregate analysis succeeds."""

        run = self._analysis_repository.get_run(analysis_run_id)
        if run is None:
            raise ValueError("NarrativeAnalysisRun not found")
        if run.status not in {
            NarrativeAnalysisRunStatus.SUCCEEDED,
            NarrativeAnalysisRunStatus.PARTIAL_FAILED,
            NarrativeAnalysisRunStatus.NEEDS_HUMAN_ACTION,
        }:
            return run
        if run.review_gate2_result is not None and run.review_gate2_route is not None:
            return run
        aggregate = self._analysis_repository.get_result(analysis_run_id)
        if aggregate is None:
            return run
        claim_handoff = getattr(self._analysis_repository, "claim_gate2_handoff", None)
        if callable(claim_handoff):
            claimed = claim_handoff(analysis_run_id)
            if claimed is None:
                current = self._analysis_repository.get_run(analysis_run_id)
                return current if current is not None else run
            run = claimed

        try:
            windows = self._analysis_repository.list_windows(analysis_run_id)
            leaf_windows = [
                window
                for window in windows
                if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
            ]
            used_chunk_ids = _stable_unique(
                chunk_id for window in leaf_windows for chunk_id in window.chunk_ids
            )
            all_document_chunks = self._source_repository.list_document_chunks(run.document_id)
            chunks_by_id = {chunk.chunk_id: chunk for chunk in all_document_chunks}
            selected_chunks = [
                chunks_by_id[chunk_id] for chunk_id in used_chunk_ids if chunk_id in chunks_by_id
            ]
            get_review_gate1 = getattr(self._source_repository, "get_review_gate1", None)
            if not callable(get_review_gate1):
                return run
            gate1 = get_review_gate1(run.document_id)
            approved_chunk_ids = (
                set(gate1.approved_chunk_bundle.chunk_ids)
                if gate1 is not None and gate1.approved_chunk_bundle is not None
                else set()
            )
            allowed_chunk_ids = [
                chunk.chunk_id for chunk in selected_chunks if chunk.chunk_id in approved_chunk_ids
            ]
            known_agent_run_ids = _stable_unique(
                window.agent_run_id for window in leaf_windows if window.agent_run_id
            )
            review_input = build_review_gate2_input(
                result=aggregate,
                project_id=run.project_id,
                document_id=run.document_id,
                allowed_chunk_ids=allowed_chunk_ids,
            )
            review_result = self._review_service.review(
                review_input,
                ReviewGate2ServiceContext(
                    source_chunks=tuple(selected_chunks),
                    known_agent_run_ids=frozenset(known_agent_run_ids),
                    agent_run_analysis_run_ids={
                        agent_run_id: run.analysis_run_id for agent_run_id in known_agent_run_ids
                    },
                ),
            )
            review_result = self._with_execution_issues(
                run=run,
                windows=windows,
                review_result=review_result,
            )
            route = self._route_for(
                run=run,
                review_result=review_result,
                windows=windows,
                review_input=review_input,
                gate1_review_id=getattr(gate1, "review_id", None),
            )
            return self._analysis_repository.save_review_gate2_artifacts(
                analysis_run_id=run.analysis_run_id,
                result=review_result,
                route=route,
            )
        except Exception:
            fail_handoff = getattr(self._analysis_repository, "fail_gate2_handoff", None)
            if callable(fail_handoff):
                return cast(
                    NarrativeAnalysisRunV1,
                    fail_handoff(
                        analysis_run_id=run.analysis_run_id,
                        failure_category="GATE2_EXECUTION_ERROR",
                    ),
                )
            raise

    def _route_for(
        self,
        *,
        run: NarrativeAnalysisRunV1,
        review_result: ReviewGate2ResultV1,
        windows: list[NarrativeAnalysisWindowV1],
        review_input: ReviewGate2InputV1,
        gate1_review_id: object,
        execution_lineage_id: str | None = None,
    ) -> NarrativeAnalysisReviewRouteV1:
        windows_by_agent_run: dict[str, list[str]] = {}
        for window in windows:
            agent_run_id = window.agent_run_id
            if isinstance(agent_run_id, str) and agent_run_id:
                windows_by_agent_run.setdefault(agent_run_id, []).append(
                    window.analysis_window_id
                )
        envelopes = {
            (envelope.proposal_schema, envelope.proposal.proposal_id): envelope
            for envelope in review_input.proposals
        }
        held = [
            decision.proposal_id
            for decision in review_result.decisions
            if decision.decision == ProposalReviewDecision.NEEDS_HUMAN_REVIEW
        ]
        diagnostics = [
            self._diagnostic_for(decision, envelopes, windows_by_agent_run)
            for decision in review_result.decisions
            if decision.decision == ProposalReviewDecision.REJECTED
        ]
        execution_bundle = self._execution_bundle_for(
            run=run,
            review_result=review_result,
            review_input=review_input,
            windows=windows,
            gate1_review_id=gate1_review_id,
            execution_lineage_id=execution_lineage_id,
        )
        incomplete_execution = any(
            issue.code == ReviewIssueCode.NARRATIVE_EXECUTION_INCOMPLETE
            for issue in execution_bundle.issues
        )
        if review_result.status == ReviewGate2RunStatus.FAILED:
            decision = ReviewGate2RoutingDecision.FAILED
            bundle = None
            diagnostics = []
            held = []
            counts = (0, 0, 0, 0)
        elif held or incomplete_execution:
            decision = ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW
            bundle = None
            counts = (
                review_result.total_count,
                review_result.approved_count,
                review_result.rejected_count,
                review_result.needs_human_review_count,
            )
        elif review_result.rejected_count:
            decision = ReviewGate2RoutingDecision.REJECTED
            bundle = None
            counts = (
                review_result.total_count,
                review_result.approved_count,
                review_result.rejected_count,
                0,
            )
        else:
            decision = ReviewGate2RoutingDecision.APPROVED
            bundle = review_result.approved_bundle
            counts = (review_result.total_count, review_result.approved_count, 0, 0)
        return NarrativeAnalysisReviewRouteV1(
            analysis_run_id=run.analysis_run_id,
            review_run_id=review_result.review_run_id,
            decision=decision,
            review_status=review_result.status,
            total_count=counts[0],
            approved_count=counts[1],
            rejected_count=counts[2],
            held_count=counts[3],
            approved_proposal_bundle=bundle,
            narrative_execution_bundle=(
                None
                if decision == ReviewGate2RoutingDecision.FAILED
                else execution_bundle
            ),
            recovery_diagnostics=diagnostics,
            held_proposal_ids=held,
        )

    @staticmethod
    def _execution_bundle_for(
        *,
        run: NarrativeAnalysisRunV1,
        review_result: ReviewGate2ResultV1,
        review_input: ReviewGate2InputV1,
        windows: list[NarrativeAnalysisWindowV1],
        gate1_review_id: object,
        execution_lineage_id: str | None,
    ) -> NarrativeExecutionBundleV1:
        """Keep audit findings while selecting only structurally safe Timeline inputs."""

        envelopes = {
            (envelope.proposal_schema, envelope.proposal.proposal_id): envelope
            for envelope in review_input.proposals
        }
        issues = _unique_review_issues(
            [
                *review_result.execution_issues,
                *(issue for decision in review_result.decisions for issue in decision.issues),
            ]
        )
        failed_windows = [
            NarrativeExecutionFailedWindowV1(
                analysis_window_id=window.analysis_window_id,
                mode=window.mode,
                chunk_ids=list(window.chunk_ids),
                status=str(window.status),
                failure_category=window.failure_category,
                safe_issue_codes=_safe_window_issue_codes(window),
                recommended_action=window.recommended_action,
            )
            for window in windows
            if window.status
            in {
                NarrativeAnalysisWindowStatus.FAILED,
                NarrativeAnalysisWindowStatus.EXHAUSTED,
                NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION,
            }
        ]
        candidates: list[ReviewableProposalEnvelopeV1] = []
        excluded_items: list[NarrativeExecutionExcludedItemV1] = []
        for decision in review_result.decisions:
            envelope = envelopes[(decision.proposal_schema, decision.proposal_id)]
            if NarrativeGate2HandoffCoordinator._is_timeline_eligible(decision):
                candidates.append(envelope)
                continue
            excluded_items.append(
                NarrativeExecutionExcludedItemV1(
                    proposal_id=decision.proposal_id,
                    proposal_schema=decision.proposal_schema,
                    mode=decision.mode,
                    reason=(
                        "Gate 2 did not establish structural, provenance, evidence, "
                        "and mode-boundary eligibility for Timeline input."
                    ),
                    issue_ids=[issue.issue_id for issue in decision.issues],
                    evidence_refs=list(envelope.aggregated_evidence_refs),
                )
            )
        evidence_refs = _stable_unique_evidence(
            evidence
            for envelope in review_input.proposals
            for evidence in envelope.aggregated_evidence_refs
        )
        try:
            status = NarrativeExecutionStatus(run.status)
        except ValueError:
            status = NarrativeExecutionStatus.NEEDS_HUMAN_ACTION
        return NarrativeExecutionBundleV1(
            bundle_id=stable_id(
                "narrative-execution-bundle",
                run.analysis_run_id,
                review_result.review_run_id,
                execution_lineage_id or "primary",
            ),
            project_id=run.project_id,
            document_id=run.document_id,
            status=status,
            candidates=candidates,
            issues=issues,
            evidence_refs=evidence_refs,
            excluded_items=excluded_items,
            failed_windows=failed_windows,
            provenance=NarrativeExecutionProvenanceV1(
                analysis_run_id=run.analysis_run_id,
                gate1_review_id=(
                    gate1_review_id
                    if isinstance(gate1_review_id, str) and gate1_review_id
                    else stable_id("gate1-review-provenance", run.document_id)
                ),
                gate2_review_run_id=review_result.review_run_id,
                recovery_attempt_id=execution_lineage_id,
                source_chunk_ids=list(review_input.allowed_chunk_ids),
                agent_run_ids=_stable_unique(
                    agent_run_id
                    for envelope in review_input.proposals
                    for agent_run_id in envelope.agent_run_ids
                ),
            ),
        )

    @staticmethod
    def _with_execution_issues(
        *,
        run: NarrativeAnalysisRunV1,
        windows: list[NarrativeAnalysisWindowV1],
        review_result: ReviewGate2ResultV1,
    ) -> ReviewGate2ResultV1:
        """Attach source-free terminal-window findings without altering proposals."""

        incomplete = [
            window
            for window in windows
            if window.status
            in {
                NarrativeAnalysisWindowStatus.FAILED,
                NarrativeAnalysisWindowStatus.EXHAUSTED,
                NarrativeAnalysisWindowStatus.NEEDS_HUMAN_ACTION,
            }
        ]
        if not incomplete:
            return review_result
        execution_issues = _unique_review_issues(
            [
                *review_result.execution_issues,
                *(
                    ReviewIssueV1(
                        issue_id=stable_id(
                            "narrative-execution-incomplete",
                            run.analysis_run_id,
                            window.analysis_window_id,
                        ),
                        code=ReviewIssueCode.NARRATIVE_EXECUTION_INCOMPLETE,
                        category=ReviewIssueCategory.EXECUTION,
                        severity=ReviewIssueSeverity.REVIEW_REQUIRED,
                        related_object_ids=[window.analysis_window_id],
                        sanitized_message=(
                            "A Narrative execution window reached a terminal incomplete state; "
                            "only successful candidates remain eligible for downstream review."
                        ),
                    )
                    for window in incomplete
                ),
            ]
        )
        status = review_result.status
        approved_bundle = review_result.approved_bundle
        if (
            status == ReviewGate2RunStatus.COMPLETED
            and not review_result.rejected_count
            and not review_result.needs_human_review_count
        ):
            # An all-approved Proposal assessment is not an all-green Narrative
            # execution when windows were terminally incomplete.
            status = ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW
            approved_bundle = None
        payload = review_result.model_dump()
        payload.update(
            {
                "schema_version": "1.1",
                "status": status,
                "approved_bundle": approved_bundle,
                "execution_issues": execution_issues,
            }
        )
        return ReviewGate2ResultV1.model_validate(payload)

    @staticmethod
    def _is_timeline_eligible(decision: ProposalReviewDecisionV1) -> bool:
        """Do not pass invalid or rejected proposal facts to Timeline."""

        required_checks = (
            decision.schema_status,
            decision.provenance_status,
            decision.evidence_status,
            decision.mode_boundary_status,
        )
        if decision.decision == ProposalReviewDecision.APPROVED:
            # Gate 2's full approval is already the deterministic proof that this
            # proposal passed all required input checks.
            return True
        return decision.decision == ProposalReviewDecision.NEEDS_HUMAN_REVIEW and all(
            status in {ReviewCheckStatus.PASSED, ReviewCheckStatus.NOT_APPLICABLE}
            for status in required_checks
        )

    @staticmethod
    def _diagnostic_for(
        decision: ProposalReviewDecisionV1,
        envelopes: Mapping[Any, ReviewableProposalEnvelopeV1],
        windows_by_agent_run: dict[str, list[str]],
    ) -> ProposalRecoveryDiagnosticV1:
        envelope = envelopes[(decision.proposal_schema, decision.proposal_id)]
        issues = sorted(decision.issues, key=lambda item: item.issue_id)
        issue_codes = _stable_unique(issue.code for issue in issues)
        source_chunk_ids = _stable_unique(
            evidence.chunk_id for evidence in envelope.aggregated_evidence_refs
        )
        eligible = bool(issue_codes) and all(
            code not in _NON_RETRYABLE_DIAGNOSTIC_CODES for code in issue_codes
        ) and any(
            issue.category in {ReviewIssueCategory.SCHEMA, ReviewIssueCategory.EVIDENCE}
            for issue in issues
        )
        return ProposalRecoveryDiagnosticV1(
            proposal_id=decision.proposal_id,
            proposal_schema=decision.proposal_schema,
            mode=decision.mode,
            agent_run_ids=list(envelope.agent_run_ids),
            analysis_window_ids=_stable_unique(
                window_id
                for agent_run_id in envelope.agent_run_ids
                for window_id in windows_by_agent_run.get(agent_run_id, [])
            ),
            issue_ids=[issue.issue_id for issue in issues],
            issue_codes=issue_codes,
            source_chunk_ids=source_chunk_ids,
            eligible_for_original_mode_rerun=eligible,
        )


def _stable_unique(values: Iterable[str | None]) -> list[str]:
    """Keep first occurrence while filtering absent audit identifiers."""

    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def _safe_window_issue_codes(window: NarrativeAnalysisWindowV1) -> list[str]:
    """Project only allowlisted diagnostic codes from a terminal window."""

    diagnostics = window.provider_error_diagnostics
    if not isinstance(diagnostics, dict):
        return []
    rule_codes = diagnostics.get("schema_error_rule_codes")
    return _stable_unique(rule_codes if isinstance(rule_codes, list) else [])


def _stable_unique_evidence(values: Iterable[EvidenceRefV1]) -> list[EvidenceRefV1]:
    """Keep EvidenceRef values in first-seen order without copying source text elsewhere."""

    seen: set[tuple[object, ...]] = set()
    result: list[EvidenceRefV1] = []
    for value in values:
        key = (
            getattr(value, "chunk_id", None),
            getattr(value, "quote_start", None),
            getattr(value, "quote_end", None),
            getattr(value, "quote_text", None),
        )
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _unique_review_issues(values: Iterable[ReviewIssueV1]) -> list[ReviewIssueV1]:
    """Keep one serialized audit issue per id without changing its contents."""

    seen: set[str] = set()
    result: list[ReviewIssueV1] = []
    for value in values:
        issue_id = getattr(value, "issue_id", None)
        if isinstance(issue_id, str) and issue_id and issue_id not in seen:
            seen.add(issue_id)
            result.append(value)
    return result


# Public compatibility alias retained for the existing worker and integrations.
NarrativeAnalysisReviewCoordinator = NarrativeGate2HandoffCoordinator
