"""Deterministic Review Gate 2 review of aggregated Narrative Analyst proposals."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    EntityProposalV1,
    EventProposalV1,
    EvidenceRefV1,
    EvidenceReviewItemV1,
    KnowledgeStateProposalV1,
    NarrativeAnalysisResultV1,
    ProposalReviewDecision,
    ProposalReviewDecisionV1,
    ReferenceResolutionBasis,
    ReferenceResolutionDecisionV1,
    ReferenceResolutionStatus,
    ReferenceTargetCandidateV1,
    RelationshipSignalProposalV1,
    ReviewableProposalEnvelopeV1,
    ReviewableProposalMode,
    ReviewCheckStatus,
    ReviewGate2InputV1,
    ReviewGate2PolicyV1,
    ReviewGate2ResultV1,
    ReviewGate2RunStatus,
    ReviewIssueCategory,
    ReviewIssueCode,
    ReviewIssueSeverity,
    ReviewIssueV1,
    ReviewMethod,
    SourceChunkV1,
    StateChangeProposalV1,
)
from comic_agent.services.id_service import stable_id


@dataclass(frozen=True)
class ReviewGate2ServiceContext:
    """Explicit, read-only scope supplied by the caller for one Gate 2 run."""

    source_chunks: tuple[SourceChunkV1, ...] = field(default_factory=tuple)
    known_agent_run_ids: frozenset[str] = field(default_factory=frozenset)
    agent_run_analysis_run_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_chunks", tuple(self.source_chunks))
        object.__setattr__(self, "known_agent_run_ids", frozenset(self.known_agent_run_ids))
        object.__setattr__(
            self, "agent_run_analysis_run_ids", dict(self.agent_run_analysis_run_ids)
        )


# Short alias for callers that prefer the name used in the service specification.
ReviewGate2Context = ReviewGate2ServiceContext


_PROPOSAL_METADATA: tuple[tuple[str, type[Any], ReviewableProposalMode], ...] = (
    ("events", EventProposalV1, ReviewableProposalMode.EVENT_EXTRACTION),
    ("entities", EntityProposalV1, ReviewableProposalMode.ENTITY_EXTRACTION),
    ("claims", ClaimProposalV1, ReviewableProposalMode.CLAIM_EXTRACTION),
    (
        "knowledge_states",
        KnowledgeStateProposalV1,
        ReviewableProposalMode.KNOWLEDGE_STATE_EXTRACTION,
    ),
    ("state_changes", StateChangeProposalV1, ReviewableProposalMode.STATE_CHANGE_EXTRACTION),
    (
        "relationship_signals",
        RelationshipSignalProposalV1,
        ReviewableProposalMode.RELATIONSHIP_SIGNAL_EXTRACTION,
    ),
    (
        "campus_content_profiles",
        CampusContentProfileProposalV1,
        ReviewableProposalMode.CAMPUS_CONTENT_PROFILE,
    ),
)

_SCHEMA_BY_TYPE: dict[type[Any], str] = {
    EventProposalV1: "EventProposalV1",
    EntityProposalV1: "EntityProposalV1",
    ClaimProposalV1: "ClaimProposalV1",
    KnowledgeStateProposalV1: "KnowledgeStateProposalV1",
    StateChangeProposalV1: "StateChangeProposalV1",
    RelationshipSignalProposalV1: "RelationshipSignalProposalV1",
    CampusContentProfileProposalV1: "CampusContentProfileProposalV1",
}

_MODE_BY_TYPE: dict[type[Any], ReviewableProposalMode] = {
    EventProposalV1: ReviewableProposalMode.EVENT_EXTRACTION,
    EntityProposalV1: ReviewableProposalMode.ENTITY_EXTRACTION,
    ClaimProposalV1: ReviewableProposalMode.CLAIM_EXTRACTION,
    KnowledgeStateProposalV1: ReviewableProposalMode.KNOWLEDGE_STATE_EXTRACTION,
    StateChangeProposalV1: ReviewableProposalMode.STATE_CHANGE_EXTRACTION,
    RelationshipSignalProposalV1: ReviewableProposalMode.RELATIONSHIP_SIGNAL_EXTRACTION,
    CampusContentProfileProposalV1: ReviewableProposalMode.CAMPUS_CONTENT_PROFILE,
}

_REFERENCE_CODES: dict[ReviewIssueCode, ReviewIssueCategory] = {
    ReviewIssueCode.REFERENCE_TARGET_NOT_FOUND: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.REFERENCE_TARGET_OUTSIDE_REVIEW_SCOPE: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.REFERENCE_SCHEMA_MISMATCH: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.UNSUPPORTED_RESOLVED_REFERENCE: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.AMBIGUOUS_ENTITY_REFERENCE: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.AMBIGUOUS_EVENT_REFERENCE: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.REQUIRED_REFERENCE_UNRESOLVED: ReviewIssueCategory.REFERENCE,
    ReviewIssueCode.CROSS_REALITY_LAYER_REFERENCE: ReviewIssueCategory.REALITY_LAYER,
}


def build_review_gate2_input(
    *,
    result: NarrativeAnalysisResultV1,
    project_id: str,
    document_id: str,
    allowed_chunk_ids: Sequence[str],
    policy: ReviewGate2PolicyV1 | None = None,
) -> ReviewGate2InputV1:
    """Build a bounded Gate 2 input from one typed aggregate result."""
    envelopes: list[ReviewableProposalEnvelopeV1] = []
    for attribute, proposal_type, mode in _PROPOSAL_METADATA:
        for aggregated in getattr(result, attribute):
            proposal = aggregated.proposal
            expected_schema = _SCHEMA_BY_TYPE[proposal_type]
            if not isinstance(proposal, proposal_type):
                # Keep malformed aggregate data visible to the service rather
                # than silently dropping it. Normal Pydantic results cannot
                # reach this branch.
                expected_schema = type(proposal).__name__
            envelopes.append(
                ReviewableProposalEnvelopeV1(
                    mode=mode,
                    proposal_schema=expected_schema,
                    proposal=proposal,
                    agent_run_ids=list(aggregated.agent_run_ids),
                    aggregated_evidence_refs=list(aggregated.evidence_refs),
                )
            )
    return ReviewGate2InputV1(
        project_id=project_id,
        document_id=document_id,
        analysis_run_id=result.analysis_run_id,
        proposals=envelopes,
        allowed_chunk_ids=list(allowed_chunk_ids),
        policy=policy or ReviewGate2PolicyV1(policy_id="review-gate-2-v1"),
    )


class ReviewGate2Service:
    """Run bounded deterministic checks without mutation or external calls."""

    def review(
        self,
        review_input: ReviewGate2InputV1,
        context: ReviewGate2ServiceContext | Mapping[str, Any] | None = None,
        *,
        source_chunks: Sequence[SourceChunkV1] | None = None,
        known_agent_run_ids: Collection[str] | None = None,
        agent_run_analysis_run_ids: Mapping[str, str] | None = None,
    ) -> ReviewGate2ResultV1:
        """Review one bounded input using only caller-supplied context."""

        try:
            bounded_context = self._context(
                context,
                source_chunks=source_chunks,
                known_agent_run_ids=known_agent_run_ids,
                agent_run_analysis_run_ids=agent_run_analysis_run_ids,
            )
            return self._review(review_input, bounded_context)
        except Exception as exc:  # pragma: no cover - defensive execution boundary
            return self._failed_result(review_input, exc)

    def _context(
        self,
        context: ReviewGate2ServiceContext | Mapping[str, Any] | None,
        *,
        source_chunks: Sequence[SourceChunkV1] | None,
        known_agent_run_ids: Collection[str] | None,
        agent_run_analysis_run_ids: Mapping[str, str] | None,
    ) -> ReviewGate2ServiceContext:
        if context is None:
            context = ReviewGate2ServiceContext()
        elif isinstance(context, Mapping):
            context = ReviewGate2ServiceContext(**context)
        if not isinstance(context, ReviewGate2ServiceContext):
            raise TypeError("context must be ReviewGate2ServiceContext or a mapping")
        if (
            source_chunks is None
            and known_agent_run_ids is None
            and agent_run_analysis_run_ids is None
        ):
            return context
        return ReviewGate2ServiceContext(
            source_chunks=tuple(context.source_chunks if source_chunks is None else source_chunks),
            known_agent_run_ids=(
                frozenset(
                    context.known_agent_run_ids
                    if known_agent_run_ids is None
                    else known_agent_run_ids
                )
            ),
            agent_run_analysis_run_ids=(
                context.agent_run_analysis_run_ids
                if agent_run_analysis_run_ids is None
                else agent_run_analysis_run_ids
            ),
        )

    def _review(
        self, value: ReviewGate2InputV1, context: ReviewGate2ServiceContext
    ) -> ReviewGate2ResultV1:
        self._validate_context_boundary(value, context)
        chunk_map = {chunk.chunk_id: chunk for chunk in context.source_chunks}
        catalog = self._candidate_catalog(value.proposals)
        duplicate_groups = self._duplicate_groups(value.proposals)
        decisions: list[ProposalReviewDecisionV1] = []
        for envelope in value.proposals:
            decisions.append(
                self._review_proposal(
                    value,
                    envelope,
                    context,
                    chunk_map,
                    catalog,
                    duplicate_groups,
                )
            )

        approved = [
            decision
            for decision in decisions
            if decision.decision == ProposalReviewDecision.APPROVED
        ]
        pending = [
            decision
            for decision in decisions
            if decision.decision == ProposalReviewDecision.NEEDS_HUMAN_REVIEW
        ]
        rejected = [
            decision
            for decision in decisions
            if decision.decision == ProposalReviewDecision.REJECTED
        ]
        review_run_id = self._review_run_id(value)
        policy = value.policy
        if pending:
            status = ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW
            bundle = None
        else:
            status = ReviewGate2RunStatus.COMPLETED
            bundle = self._approved_bundle(value, review_run_id, approved)
        return ReviewGate2ResultV1(
            review_run_id=review_run_id,
            project_id=value.project_id,
            document_id=value.document_id,
            analysis_run_id=value.analysis_run_id,
            status=status,
            policy=policy,
            decisions=decisions,
            total_count=len(decisions),
            approved_count=len(approved),
            rejected_count=len(rejected),
            needs_human_review_count=len(pending),
            approved_bundle=bundle,
            execution_issues=[],
        )

    def _validate_context_boundary(
        self, value: ReviewGate2InputV1, context: ReviewGate2ServiceContext
    ) -> None:
        """Reject ambiguous or out-of-scope caller context before any review work."""

        chunk_ids = [chunk.chunk_id for chunk in context.source_chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("context source chunk ids must be unique")
        if any(chunk_id not in value.allowed_chunk_ids for chunk_id in chunk_ids):
            raise ValueError("context source chunks must be within allowed chunk scope")
        if not set(context.agent_run_analysis_run_ids).issubset(context.known_agent_run_ids):
            raise ValueError("agent run analysis mapping must be within known agent run scope")

    def _review_proposal(
        self,
        value: ReviewGate2InputV1,
        envelope: ReviewableProposalEnvelopeV1,
        context: ReviewGate2ServiceContext,
        chunk_map: dict[str, SourceChunkV1],
        catalog: dict[str, list[tuple[str, str, str, Any]]],
        duplicate_groups: dict[str, list[ReviewableProposalEnvelopeV1]],
    ) -> ProposalReviewDecisionV1:
        proposal = envelope.proposal
        proposal_schema = envelope.proposal_schema
        proposal_id = str(getattr(proposal, "proposal_id", "unknown-proposal"))
        key = (proposal_schema, proposal_id)
        issues: list[ReviewIssueV1] = []
        schema_status = ReviewCheckStatus.PASSED
        provenance_status = ReviewCheckStatus.PASSED
        mode_boundary_status = ReviewCheckStatus.PASSED

        actual_schema = _SCHEMA_BY_TYPE.get(type(proposal))
        actual_mode = _MODE_BY_TYPE.get(type(proposal))
        if actual_schema is None:
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.UNSUPPORTED_PROPOSAL_SCHEMA,
                    ReviewIssueCategory.SCHEMA,
                    ReviewIssueSeverity.BLOCKING,
                )
            )
            schema_status = ReviewCheckStatus.FAILED
        else:
            if proposal_schema != actual_schema:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.PROPOSAL_SCHEMA_MISMATCH,
                        ReviewIssueCategory.SCHEMA,
                        ReviewIssueSeverity.BLOCKING,
                    )
                )
                schema_status = ReviewCheckStatus.FAILED
            if envelope.mode != actual_mode:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.MODE_SCHEMA_MISMATCH,
                        ReviewIssueCategory.MODE_BOUNDARY,
                        ReviewIssueSeverity.BLOCKING,
                    )
                )
                mode_boundary_status = ReviewCheckStatus.FAILED
        if self._contains_forbidden_payload(proposal):
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.MODE_BOUNDARY_VIOLATION,
                    ReviewIssueCategory.MODE_BOUNDARY,
                    ReviewIssueSeverity.BLOCKING,
                )
            )
            mode_boundary_status = ReviewCheckStatus.FAILED

        provenance_issues = self._provenance_issues(value, envelope, context, key)
        issues.extend(provenance_issues)
        if provenance_issues:
            provenance_status = ReviewCheckStatus.FAILED

        evidence_reviews, evidence_issues = self._evidence_reviews(value, envelope, chunk_map, key)
        issues.extend(evidence_issues)
        if evidence_issues:
            evidence_status = ReviewCheckStatus.FAILED
        else:
            evidence_status = ReviewCheckStatus.PASSED
        if not envelope.aggregated_evidence_refs:
            evidence_status = ReviewCheckStatus.FAILED
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.EVIDENCE_MISSING,
                    ReviewIssueCategory.EVIDENCE,
                    ReviewIssueSeverity.BLOCKING,
                )
            )
        if not self._proposal_evidence_is_retained(envelope):
            evidence_status = ReviewCheckStatus.FAILED
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.EVIDENCE_MISSING,
                    ReviewIssueCategory.EVIDENCE,
                    ReviewIssueSeverity.BLOCKING,
                )
            )

        reference_decisions, reference_issues = self._references(value, envelope, catalog, key)
        issues.extend(reference_issues)
        if any(issue.severity == ReviewIssueSeverity.BLOCKING for issue in reference_issues):
            schema_status = ReviewCheckStatus.FAILED
        elif any(
            issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED for issue in reference_issues
        ):
            schema_status = ReviewCheckStatus.NEEDS_HUMAN_REVIEW

        duplicate_issues = self._duplicate_issues(value, key, duplicate_groups)
        issues.extend(duplicate_issues)
        if duplicate_issues:
            if any(issue.severity == ReviewIssueSeverity.BLOCKING for issue in duplicate_issues):
                schema_status = ReviewCheckStatus.FAILED
            else:
                schema_status = ReviewCheckStatus.NEEDS_HUMAN_REVIEW

        issue_ids = {issue.issue_id for issue in issues}
        issues = [issue for issue in issues if issue.issue_id in issue_ids]
        has_blocking = any(issue.severity == ReviewIssueSeverity.BLOCKING for issue in issues)
        has_review = any(issue.severity == ReviewIssueSeverity.REVIEW_REQUIRED for issue in issues)
        if has_blocking:
            decision = ProposalReviewDecision.REJECTED
        elif has_review:
            decision = ProposalReviewDecision.NEEDS_HUMAN_REVIEW
        else:
            decision = ProposalReviewDecision.APPROVED
        return ProposalReviewDecisionV1(
            decision_id=self._decision_id(value, key),
            analysis_run_id=value.analysis_run_id,
            proposal_id=proposal_id,
            proposal_schema=proposal_schema,
            mode=envelope.mode,
            decision=decision,
            schema_status=schema_status,
            provenance_status=provenance_status,
            evidence_status=evidence_status,
            mode_boundary_status=mode_boundary_status,
            evidence_reviews=evidence_reviews,
            reference_decisions=reference_decisions,
            issues=issues,
            review_method=ReviewMethod.DETERMINISTIC,
            reviewed_by="review-gate-2-deterministic",
        )

    def _provenance_issues(
        self,
        value: ReviewGate2InputV1,
        envelope: ReviewableProposalEnvelopeV1,
        context: ReviewGate2ServiceContext,
        key: tuple[str, str],
    ) -> list[ReviewIssueV1]:
        issues: list[ReviewIssueV1] = []
        if not envelope.agent_run_ids:
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.PROVENANCE_MISSING,
                    ReviewIssueCategory.PROVENANCE,
                    ReviewIssueSeverity.BLOCKING,
                )
            )
        for agent_run_id in envelope.agent_run_ids:
            if agent_run_id not in context.known_agent_run_ids:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.AGENT_RUN_NOT_FOUND,
                        ReviewIssueCategory.PROVENANCE,
                        ReviewIssueSeverity.BLOCKING,
                        field_path="agent_run_ids",
                    )
                )
            mapped_run = context.agent_run_analysis_run_ids.get(agent_run_id)
            if mapped_run is not None and mapped_run != value.analysis_run_id:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.ANALYSIS_RUN_MISMATCH,
                        ReviewIssueCategory.PROVENANCE,
                        ReviewIssueSeverity.BLOCKING,
                        field_path="agent_run_ids",
                    )
                )
        return self._unique_issues(issues)

    def _evidence_reviews(
        self,
        value: ReviewGate2InputV1,
        envelope: ReviewableProposalEnvelopeV1,
        chunk_map: dict[str, SourceChunkV1],
        key: tuple[str, str],
    ) -> tuple[list[EvidenceReviewItemV1], list[ReviewIssueV1]]:
        reviews: list[EvidenceReviewItemV1] = []
        all_issues: list[ReviewIssueV1] = []
        for index, raw_ref in enumerate(envelope.aggregated_evidence_refs):
            ref = self._coerce_evidence(raw_ref)
            issues: list[ReviewIssueV1] = []
            if ref.chunk_id not in value.allowed_chunk_ids:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.EVIDENCE_OUTSIDE_ANALYSIS_SCOPE,
                        ReviewIssueCategory.EVIDENCE,
                        ReviewIssueSeverity.BLOCKING,
                        evidence_index=index,
                    )
                )
            chunk = chunk_map.get(ref.chunk_id)
            if chunk is None:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.EVIDENCE_CHUNK_NOT_FOUND,
                        ReviewIssueCategory.EVIDENCE,
                        ReviewIssueSeverity.BLOCKING,
                        evidence_index=index,
                    )
                )
            else:
                if chunk.project_id != value.project_id or chunk.document_id != value.document_id:
                    issues.append(
                        self._issue(
                            value,
                            key,
                            ReviewIssueCode.EVIDENCE_CHUNK_NOT_FOUND,
                            ReviewIssueCategory.EVIDENCE,
                            ReviewIssueSeverity.BLOCKING,
                            evidence_index=index,
                        )
                    )
                if ref.quote_text is None or ref.quote_text not in chunk.text:
                    issues.append(
                        self._issue(
                            value,
                            key,
                            ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND,
                            ReviewIssueCategory.EVIDENCE,
                            ReviewIssueSeverity.BLOCKING,
                            evidence_index=index,
                        )
                    )
                start, end = ref.quote_start, ref.quote_end
                if (start is None) != (end is None):
                    issues.append(
                        self._issue(
                            value,
                            key,
                            ReviewIssueCode.EVIDENCE_RANGE_INCOMPLETE,
                            ReviewIssueCategory.EVIDENCE,
                            ReviewIssueSeverity.BLOCKING,
                            evidence_index=index,
                        )
                    )
                elif start is not None and end is not None:
                    if start < 0 or end < 0 or start >= end or end > len(chunk.text):
                        issues.append(
                            self._issue(
                                value,
                                key,
                                ReviewIssueCode.EVIDENCE_RANGE_OUT_OF_BOUNDS,
                                ReviewIssueCategory.EVIDENCE,
                                ReviewIssueSeverity.BLOCKING,
                                evidence_index=index,
                            )
                        )
                    elif ref.quote_text is None or chunk.text[start:end] != ref.quote_text:
                        issues.append(
                            self._issue(
                                value,
                                key,
                                ReviewIssueCode.EVIDENCE_OFFSET_MISMATCH,
                                ReviewIssueCategory.EVIDENCE,
                                ReviewIssueSeverity.BLOCKING,
                                evidence_index=index,
                            )
                        )
            issues = self._unique_issues(issues)
            all_issues.extend(issues)
            reviews.append(
                EvidenceReviewItemV1(
                    evidence_index=index,
                    evidence_ref=ref,
                    status=ReviewCheckStatus.FAILED if issues else ReviewCheckStatus.PASSED,
                    issues=issues,
                )
            )
        return reviews, self._unique_issues(all_issues)

    def _references(
        self,
        value: ReviewGate2InputV1,
        envelope: ReviewableProposalEnvelopeV1,
        catalog: dict[str, list[tuple[str, str, str, Any]]],
        key: tuple[str, str],
    ) -> tuple[list[ReferenceResolutionDecisionV1], list[ReviewIssueV1]]:
        specs = self._reference_specs(envelope.proposal)
        decisions: list[ReferenceResolutionDecisionV1] = []
        issues: list[ReviewIssueV1] = []
        for path, mention, expected, selected_id, selected_schema, status, required in specs:
            decision, decision_issues = self._resolve_reference(
                value,
                key,
                path,
                mention,
                expected,
                selected_id,
                selected_schema,
                status,
                required,
                catalog,
                envelope.proposal,
            )
            decisions.append(decision)
            issues.extend(decision_issues)
        return decisions, self._unique_issues(issues)

    def _resolve_reference(
        self,
        value: ReviewGate2InputV1,
        key: tuple[str, str],
        path: str,
        mention: str | None,
        expected: list[str],
        selected_id: str | None,
        selected_schema: str | None,
        status: str | None,
        required: bool,
        catalog: dict[str, list[tuple[str, str, str, Any]]],
        source_proposal: Any,
    ) -> tuple[ReferenceResolutionDecisionV1, list[ReviewIssueV1]]:
        issues: list[ReviewIssueV1] = []
        explicit = status == ReferenceResolutionStatus.RESOLVED.value or selected_id is not None
        if explicit:
            if selected_id is None:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.UNSUPPORTED_RESOLVED_REFERENCE,
                        ReviewIssueCategory.REFERENCE,
                        ReviewIssueSeverity.BLOCKING,
                        field_path=path,
                    )
                )
                return self._rejected_reference(path, mention, expected, required, issues), issues
            if selected_schema is None or selected_schema not in expected:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.REFERENCE_SCHEMA_MISMATCH,
                        ReviewIssueCategory.REFERENCE,
                        ReviewIssueSeverity.BLOCKING,
                        field_path=path,
                    )
                )
                return self._rejected_reference(path, mention, expected, required, issues), issues
            candidate = next(
                (item for item in catalog.get(selected_schema, []) if item[0] == selected_id),
                None,
            )
            if candidate is None:
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.REFERENCE_TARGET_NOT_FOUND,
                        ReviewIssueCategory.REFERENCE,
                        ReviewIssueSeverity.BLOCKING,
                        field_path=path,
                    )
                )
                return self._rejected_reference(path, mention, expected, required, issues), issues
            if not self._reality_matches(source_proposal, candidate[3]):
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.CROSS_REALITY_LAYER_REFERENCE,
                        ReviewIssueCategory.REALITY_LAYER,
                        ReviewIssueSeverity.BLOCKING,
                        field_path=path,
                    )
                )
                return self._rejected_reference(path, mention, expected, required, issues), issues
            ref_candidate = self._candidate(
                candidate, ReferenceResolutionBasis.EXPLICIT_PROPOSAL_ID
            )
            return ReferenceResolutionDecisionV1(
                reference_path=path,
                mention_text=mention,
                expected_target_schemas=expected,
                required_for_downstream=required,
                status=ReferenceResolutionStatus.RESOLVED,
                candidates=[ref_candidate],
                selected_target_proposal_id=selected_id,
                selected_target_proposal_schema=selected_schema,
                resolution_basis=ReferenceResolutionBasis.EXPLICIT_PROPOSAL_ID,
            ), issues

        candidates = [
            candidate
            for schema in expected
            for candidate in catalog.get(schema, [])
            if mention is not None and candidate[2] == mention
        ]
        if len(candidates) == 1:
            candidate = candidates[0]
            if not self._reality_matches(source_proposal, candidate[3]):
                issues.append(
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.CROSS_REALITY_LAYER_REFERENCE,
                        ReviewIssueCategory.REALITY_LAYER,
                        ReviewIssueSeverity.BLOCKING,
                        field_path=path,
                    )
                )
                return self._rejected_reference(path, mention, expected, required, issues), issues
            return ReferenceResolutionDecisionV1(
                reference_path=path,
                mention_text=mention,
                expected_target_schemas=expected,
                required_for_downstream=required,
                status=ReferenceResolutionStatus.RESOLVED,
                candidates=[
                    self._candidate(candidate, ReferenceResolutionBasis.EXACT_UNIQUE_MENTION)
                ],
                selected_target_proposal_id=candidate[0],
                selected_target_proposal_schema=candidate[1],
                resolution_basis=ReferenceResolutionBasis.EXACT_UNIQUE_MENTION,
            ), issues
        if len(candidates) > 1:
            code = (
                ReviewIssueCode.AMBIGUOUS_EVENT_REFERENCE
                if set(expected) == {"EventProposalV1"}
                else ReviewIssueCode.AMBIGUOUS_ENTITY_REFERENCE
            )
            issues.append(
                self._issue(
                    value,
                    key,
                    code,
                    ReviewIssueCategory.REFERENCE,
                    ReviewIssueSeverity.REVIEW_REQUIRED,
                    field_path=path,
                )
            )
            decision = ReferenceResolutionDecisionV1(
                reference_path=path,
                mention_text=mention,
                expected_target_schemas=expected,
                required_for_downstream=required,
                status=ReferenceResolutionStatus.AMBIGUOUS,
                candidates=[
                    self._candidate(candidate, ReferenceResolutionBasis.EXACT_UNIQUE_MENTION)
                    for candidate in candidates
                ],
                resolution_basis=ReferenceResolutionBasis.NONE,
                issues=[issues[-1]],
            )
            return decision, issues
        if required:
            issues.append(
                self._issue(
                    value,
                    key,
                    ReviewIssueCode.REQUIRED_REFERENCE_UNRESOLVED,
                    ReviewIssueCategory.REFERENCE,
                    ReviewIssueSeverity.REVIEW_REQUIRED,
                    field_path=path,
                )
            )
            decision = ReferenceResolutionDecisionV1(
                reference_path=path,
                mention_text=mention,
                expected_target_schemas=expected,
                required_for_downstream=True,
                status=ReferenceResolutionStatus.UNRESOLVED,
                resolution_basis=ReferenceResolutionBasis.NONE,
                issues=[issues[-1]],
            )
            return decision, issues
        return ReferenceResolutionDecisionV1(
            reference_path=path,
            mention_text=mention,
            expected_target_schemas=expected,
            required_for_downstream=False,
            status=ReferenceResolutionStatus.UNRESOLVED,
            resolution_basis=ReferenceResolutionBasis.NONE,
        ), issues

    def _reference_specs(
        self, proposal: Any
    ) -> list[tuple[str, str | None, list[str], str | None, str | None, str | None, bool]]:
        specs: list[
            tuple[str, str | None, list[str], str | None, str | None, str | None, bool]
        ] = []
        if isinstance(proposal, EventProposalV1):
            for index, participant_id in enumerate(proposal.participant_ids):
                specs.append(
                    (
                        f"participant_ids[{index}]",
                        participant_id,
                        ["EntityProposalV1"],
                        participant_id,
                        "EntityProposalV1",
                        "RESOLVED",
                        False,
                    )
                )
            for index, participant_mention in enumerate(proposal.participant_mentions):
                specs.append(
                    (
                        f"participant_mentions[{index}]",
                        participant_mention.mention_text,
                        ["EntityProposalV1"],
                        participant_mention.proposal_id,
                        participant_mention.proposal_schema,
                        str(participant_mention.resolution_status),
                        False,
                    )
                )
            if proposal.location_id is not None:
                specs.append(
                    (
                        "location_id",
                        proposal.location_id,
                        ["EntityProposalV1"],
                        proposal.location_id,
                        "EntityProposalV1",
                        "RESOLVED",
                        False,
                    )
                )
            if proposal.location_mention is not None:
                location = proposal.location_mention
                specs.append(
                    (
                        "location_mention",
                        location.mention_text,
                        ["EntityProposalV1"],
                        location.proposal_id,
                        location.proposal_schema,
                        str(location.resolution_status),
                        False,
                    )
                )
        elif isinstance(proposal, ClaimProposalV1):
            if proposal.source_id is not None:
                expected = (
                    ["EntityProposalV1"]
                    if str(proposal.source_type) == "CHARACTER"
                    else ["EntityProposalV1", "EventProposalV1", "ClaimProposalV1"]
                )
                specs.append(
                    (
                        "source_id",
                        proposal.source_id,
                        expected,
                        proposal.source_id,
                        "EntityProposalV1"
                        if str(proposal.source_type) == "CHARACTER"
                        else None,
                        "RESOLVED",
                        False,
                    )
                )
            if proposal.source_reference is not None:
                source_reference = proposal.source_reference
                expected = (
                    ["EntityProposalV1"]
                    if str(proposal.source_type) == "CHARACTER"
                    else ["EntityProposalV1", "EventProposalV1", "ClaimProposalV1"]
                )
                specs.append(
                    (
                        "source_reference",
                        source_reference.mention_text,
                        expected,
                        source_reference.proposal_id,
                        source_reference.proposal_schema,
                        str(source_reference.resolution_status),
                        False,
                    )
                )
            if proposal.target_event_id is not None:
                specs.append(
                    (
                        "target_event_id",
                        proposal.claim_text,
                        ["EventProposalV1"],
                        proposal.target_event_id,
                        "EventProposalV1",
                        "RESOLVED",
                        False,
                    )
                )
            if proposal.target_event_reference is not None:
                target_reference = proposal.target_event_reference
                specs.append(
                    (
                        "target_event_reference",
                        target_reference.mention_text,
                        ["EventProposalV1"],
                        target_reference.proposal_id,
                        target_reference.proposal_schema,
                        str(target_reference.resolution_status),
                        False,
                    )
                )
        elif isinstance(proposal, KnowledgeStateProposalV1):
            if proposal.subject is not None:
                specs.append(
                    (
                        "subject",
                        proposal.subject.mention_text,
                        ["EntityProposalV1"],
                        proposal.subject.entity_proposal_id,
                        "EntityProposalV1" if proposal.subject.entity_proposal_id else None,
                        str(proposal.subject.resolution_status),
                        False,
                    )
                )
            if proposal.target is not None:
                expected = {
                    "CLAIM": ["ClaimProposalV1"],
                    "EVENT": ["EventProposalV1"],
                    "ENTITY_FACT": ["EntityProposalV1"],
                    "WORLD_FACT": ["ClaimProposalV1", "EventProposalV1", "EntityProposalV1"],
                    "UNKNOWN": ["ClaimProposalV1", "EventProposalV1", "EntityProposalV1"],
                }.get(
                    str(proposal.target.target_kind),
                    ["ClaimProposalV1", "EventProposalV1", "EntityProposalV1"],
                )
                specs.append(
                    (
                        "target",
                        proposal.target.target_text,
                        expected,
                        proposal.target.proposal_id,
                        proposal.target.proposal_schema,
                        str(proposal.target.resolution_status),
                        False,
                    )
                )
            for path, knowledge_anchor in (
                ("valid_from", proposal.valid_from),
                ("valid_until", proposal.valid_until),
            ):
                if knowledge_anchor is not None and (
                    knowledge_anchor.event_proposal_id is not None
                    or knowledge_anchor.anchor_text is not None
                ):
                    specs.append(
                        (
                            path,
                            knowledge_anchor.anchor_text,
                            ["EventProposalV1"],
                            knowledge_anchor.event_proposal_id,
                            ("EventProposalV1" if knowledge_anchor.event_proposal_id else None),
                            str(knowledge_anchor.resolution_status),
                            False,
                        )
                    )
            if proposal.supporting_claim_proposal_id is not None:
                specs.append(
                    (
                        "supporting_claim_proposal_id",
                        None,
                        ["ClaimProposalV1"],
                        proposal.supporting_claim_proposal_id,
                        "ClaimProposalV1",
                        "RESOLVED",
                        False,
                    )
                )
        elif isinstance(proposal, StateChangeProposalV1):
            if proposal.event is not None:
                specs.append(
                    (
                        "event",
                        proposal.event.event_summary,
                        ["EventProposalV1"],
                        proposal.event.event_proposal_id,
                        proposal.event.proposal_schema,
                        str(proposal.event.resolution_status),
                        False,
                    )
                )
            if proposal.target is not None:
                specs.append(
                    (
                        "target",
                        proposal.target.mention_text,
                        ["EntityProposalV1"],
                        proposal.target.entity_proposal_id,
                        proposal.target.proposal_schema,
                        str(proposal.target.resolution_status),
                        False,
                    )
                )
        elif isinstance(proposal, RelationshipSignalProposalV1):
            for path, relationship_participant in (
                ("subject", proposal.subject),
                ("counterpart", proposal.counterpart),
                ("source_speaker", proposal.source_speaker),
            ):
                if relationship_participant is not None:
                    specs.append(
                        (
                            path,
                            relationship_participant.mention_text,
                            ["EntityProposalV1"],
                            relationship_participant.entity_proposal_id,
                            relationship_participant.proposal_schema,
                            str(relationship_participant.resolution_status),
                            False,
                        )
                    )
            if proposal.context_event is not None:
                specs.append(
                    (
                        "context_event",
                        proposal.context_event.event_summary,
                        ["EventProposalV1"],
                        proposal.context_event.event_proposal_id,
                        proposal.context_event.proposal_schema,
                        str(proposal.context_event.resolution_status),
                        False,
                    )
                )
            relationship_anchor = proposal.temporal_anchor
            if (
                relationship_anchor.event_proposal_id is not None
                or relationship_anchor.anchor_text is not None
            ):
                specs.append(
                    (
                        "temporal_anchor",
                        relationship_anchor.anchor_text,
                        ["EventProposalV1"],
                        relationship_anchor.event_proposal_id,
                        relationship_anchor.proposal_schema,
                        str(relationship_anchor.resolution_status),
                        False,
                    )
                )
        return specs

    def _candidate_catalog(
        self, envelopes: Sequence[ReviewableProposalEnvelopeV1]
    ) -> dict[str, list[tuple[str, str, str, Any]]]:
        catalog: dict[str, list[tuple[str, str, str, Any]]] = defaultdict(list)
        for envelope in envelopes:
            proposal = envelope.proposal
            schema = envelope.proposal_schema
            proposal_id = str(getattr(proposal, "proposal_id", ""))
            mention = None
            if isinstance(proposal, EntityProposalV1):
                mention = proposal.canonical_name
            elif isinstance(proposal, EventProposalV1):
                mention = proposal.summary
            elif isinstance(proposal, ClaimProposalV1):
                mention = proposal.claim_text
            if mention is not None:
                catalog[schema].append((proposal_id, schema, mention, proposal))
        return catalog

    def _candidate(
        self, candidate: tuple[str, str, str, Any], basis: ReferenceResolutionBasis
    ) -> ReferenceTargetCandidateV1:
        return ReferenceTargetCandidateV1(
            target_proposal_id=candidate[0],
            target_proposal_schema=candidate[1],
            match_basis=basis,
            source_mention=candidate[2],
        )

    def _rejected_reference(
        self,
        path: str,
        mention: str | None,
        expected: list[str],
        required: bool,
        issues: list[ReviewIssueV1],
    ) -> ReferenceResolutionDecisionV1:
        return ReferenceResolutionDecisionV1(
            reference_path=path,
            mention_text=mention,
            expected_target_schemas=expected,
            required_for_downstream=required,
            status=ReferenceResolutionStatus.REJECTED,
            resolution_basis=ReferenceResolutionBasis.NONE,
            issues=issues,
        )

    def _proposal_evidence_is_retained(self, envelope: ReviewableProposalEnvelopeV1) -> bool:
        aggregate = {_evidence_key(ref) for ref in envelope.aggregated_evidence_refs}
        return all(_evidence_key(ref) in aggregate for ref in envelope.proposal.evidence_refs)

    def _duplicate_groups(
        self, envelopes: Sequence[ReviewableProposalEnvelopeV1]
    ) -> dict[str, list[ReviewableProposalEnvelopeV1]]:
        groups: dict[str, list[ReviewableProposalEnvelopeV1]] = defaultdict(list)
        for envelope in envelopes:
            payload = envelope.proposal.model_dump(mode="json")
            payload.pop("proposal_id", None)
            key = json.dumps(
                [envelope.proposal_schema, payload], sort_keys=True, separators=(",", ":")
            )
            groups[key].append(envelope)
        return groups

    def _duplicate_issues(
        self,
        value: ReviewGate2InputV1,
        key: tuple[str, str],
        duplicate_groups: dict[str, list[ReviewableProposalEnvelopeV1]],
    ) -> list[ReviewIssueV1]:
        for group in duplicate_groups.values():
            ids = {
                (item.proposal_schema, str(getattr(item.proposal, "proposal_id", "")))
                for item in group
            }
            current = key in ids
            if current and len(ids) > 1:
                return [
                    self._issue(
                        value,
                        key,
                        ReviewIssueCode.EXACT_DUPLICATE,
                        ReviewIssueCategory.DUPLICATE,
                        ReviewIssueSeverity.BLOCKING,
                    )
                ]
        return []

    def _approved_bundle(
        self,
        value: ReviewGate2InputV1,
        review_run_id: str,
        approved: Sequence[ProposalReviewDecisionV1],
    ) -> ApprovedProposalBundleV1:
        by_key = {
            (item.proposal_schema, str(getattr(item.proposal, "proposal_id", ""))): item
            for item in value.proposals
        }
        items = [
            ApprovedProposalItemV1(
                source=by_key[(decision.proposal_schema, decision.proposal_id)],
                review_decision_id=decision.decision_id,
                reference_decisions=decision.reference_decisions,
            )
            for decision in approved
        ]
        decision_ids = [item.review_decision_id for item in items]
        return ApprovedProposalBundleV1(
            bundle_id=stable_id(
                "review-gate-2-bundle", value.analysis_run_id, value.policy.policy_id
            ),
            project_id=value.project_id,
            document_id=value.document_id,
            analysis_run_id=value.analysis_run_id,
            review_run_id=review_run_id,
            policy_id=value.policy.policy_id,
            approved_proposals=items,
            review_decision_ids=decision_ids,
            unresolved_nonblocking_references=[
                reference
                for decision in approved
                for reference in decision.reference_decisions
                if reference.status == ReferenceResolutionStatus.UNRESOLVED
                and not reference.required_for_downstream
            ],
        )

    def _failed_result(self, value: ReviewGate2InputV1, exc: Exception) -> ReviewGate2ResultV1:
        issue = ReviewIssueV1(
            issue_id=stable_id(
                "review-gate-2-execution-issue", value.analysis_run_id, value.policy.policy_id
            ),
            code=ReviewIssueCode.REVIEW_EXECUTION_FAILED,
            category=ReviewIssueCategory.EXECUTION,
            severity=ReviewIssueSeverity.BLOCKING,
            sanitized_message=f"deterministic Gate 2 review failed with {type(exc).__name__}",
        )
        return ReviewGate2ResultV1(
            review_run_id=self._review_run_id(value),
            project_id=value.project_id,
            document_id=value.document_id,
            analysis_run_id=value.analysis_run_id,
            status=ReviewGate2RunStatus.FAILED,
            policy=value.policy,
            decisions=[],
            total_count=0,
            approved_count=0,
            rejected_count=0,
            needs_human_review_count=0,
            approved_bundle=None,
            execution_issues=[issue],
        )

    def _issue(
        self,
        value: ReviewGate2InputV1,
        key: tuple[str, str],
        code: ReviewIssueCode,
        category: ReviewIssueCategory,
        severity: ReviewIssueSeverity,
        *,
        field_path: str | None = None,
        evidence_index: int | None = None,
    ) -> ReviewIssueV1:
        suffix = field_path or ""
        if evidence_index is not None:
            suffix = f"{suffix}:{evidence_index}"
        return ReviewIssueV1(
            issue_id=stable_id(
                "review-gate-2-issue", value.analysis_run_id, key[0], key[1], code.value, suffix
            ),
            code=code,
            category=category,
            severity=severity,
            field_path=field_path,
            evidence_index=evidence_index,
            related_object_ids=[key[1]],
            sanitized_message=f"deterministic Gate 2 check reported {code.value}",
        )

    def _unique_issues(self, issues: Sequence[ReviewIssueV1]) -> list[ReviewIssueV1]:
        seen: set[str] = set()
        result: list[ReviewIssueV1] = []
        for issue in issues:
            if issue.issue_id not in seen:
                seen.add(issue.issue_id)
                result.append(issue)
        return result

    def _coerce_evidence(self, ref: EvidenceRefV1 | Any) -> EvidenceRefV1:
        if isinstance(ref, EvidenceRefV1):
            return ref
        try:
            return EvidenceRefV1.model_validate(ref)
        except Exception:
            return EvidenceRefV1.model_construct(
                chunk_id=str(getattr(ref, "chunk_id", "invalid-chunk")),
                quote_start=getattr(ref, "quote_start", None),
                quote_end=getattr(ref, "quote_end", None),
                quote_text=getattr(ref, "quote_text", None),
            )

    def _contains_forbidden_payload(self, proposal: Any) -> bool:
        if not hasattr(proposal, "model_dump"):
            return True
        payload = proposal.model_dump()
        forbidden = {
            "canonical_story_bible",
            "commit_plan",
            "provider_response",
            "raw_provider_response",
            "canonical_id",
        }

        def walk(value: Any) -> bool:
            if isinstance(value, dict):
                return any(key in forbidden or walk(item) for key, item in value.items())
            if isinstance(value, list):
                return any(walk(item) for item in value)
            return False

        return walk(payload)

    def _reality_matches(self, source: Any, target: Any) -> bool:
        source_layer = getattr(source, "reality_layer", None)
        target_layer = getattr(target, "reality_layer", None)
        return source_layer is None or target_layer is None or source_layer == target_layer

    def _review_run_id(self, value: ReviewGate2InputV1) -> str:
        return stable_id("review-gate-2", value.analysis_run_id, value.policy.policy_id)

    def _decision_id(self, value: ReviewGate2InputV1, key: tuple[str, str]) -> str:
        return stable_id("review-gate-2-decision", value.analysis_run_id, key[0], key[1])


def _evidence_key(ref: EvidenceRefV1 | Any) -> tuple[Any, ...]:
    return (
        getattr(ref, "chunk_id", None),
        getattr(ref, "quote_start", None),
        getattr(ref, "quote_end", None),
        getattr(ref, "quote_text", None),
    )
