"""Automatic, bounded handoff from a completed Narrative Analyst run to Gate 2."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas import (
    NarrativeAnalysisReviewRouteV1,
    NarrativeAnalysisRunStatus,
    ProposalRecoveryDiagnosticV1,
    ProposalReviewDecision,
    ProposalReviewDecisionV1,
    ReviewableProposalEnvelopeV1,
    ReviewGate2InputV1,
    ReviewGate2ResultV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
)
from comic_agent.schemas.workflow import (
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
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
        if run.status != NarrativeAnalysisRunStatus.SUCCEEDED:
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
        try:
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
            route = self._route_for(
                run=run,
                review_result=review_result,
                windows=leaf_windows,
                review_input=review_input,
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
        if review_result.status == ReviewGate2RunStatus.FAILED:
            decision = ReviewGate2RoutingDecision.FAILED
            bundle = None
            diagnostics = []
            held = []
            counts = (0, 0, 0, 0)
        elif held:
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
            recovery_diagnostics=diagnostics,
            held_proposal_ids=held,
        )

    @staticmethod
    def _diagnostic_for(
        decision: ProposalReviewDecisionV1,
        envelopes: Mapping[Any, ReviewableProposalEnvelopeV1],
        windows_by_agent_run: dict[str, list[str]],
    ) -> ProposalRecoveryDiagnosticV1:
        envelope = envelopes[(decision.proposal_schema, decision.proposal_id)]
        issues = sorted(decision.issues, key=lambda item: item.issue_id)
        issue_codes = [issue.code for issue in issues]
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


# Public compatibility alias retained for the existing worker and integrations.
NarrativeAnalysisReviewCoordinator = NarrativeGate2HandoffCoordinator
