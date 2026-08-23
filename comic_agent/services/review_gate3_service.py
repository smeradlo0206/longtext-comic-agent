"""Deterministic, bounded structural review for Timeline candidate output."""

from collections import defaultdict
from collections.abc import Iterable

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import TemporalRelation, TemporalRelationProposalV1
from comic_agent.schemas.timeline import (
    ApprovedTimelineBundleV1,
    NarrativeTimelineReviewRouteV1,
    ReviewGate3Decision,
    ReviewGate3ResultV1,
    TimelineGate3IssueCode,
    TimelineGate3IssueSeverity,
    TimelineGate3IssueV1,
)
from comic_agent.services.id_service import stable_id


class ReviewGate3Service:
    """Review explicit ids/evidence/ordering only; never infer or repair facts."""

    _RECOVERABLE = {
        TimelineGate3IssueCode.TEMPORAL_CYCLE,
        TimelineGate3IssueCode.UNSUPPORTED_RELATION,
        TimelineGate3IssueCode.EVIDENCE_OUT_OF_SCOPE,
        TimelineGate3IssueCode.UNKNOWN_EVENT_REFERENCE,
        TimelineGate3IssueCode.CONFLICTING_RELATIONS,
    }

    def review(
        self,
        *,
        project_id: str,
        source_approved_proposal_bundle_id: str | None,
        source_narrative_execution_bundle_id: str | None = None,
        timeline_run_id: str,
        reviewer_agent_run_id: str,
        event_ids: Iterable[str],
        temporal_relations: Iterable[TemporalRelationProposalV1],
        evidence_refs: Iterable[EvidenceRefV1],
        source_gate2_review_id: str = "gate2-review-unknown",
        source_gate2_route_id: str = "gate2-route-unknown",
    ) -> tuple[ReviewGate3ResultV1, NarrativeTimelineReviewRouteV1]:
        ids = list(dict.fromkeys(event_ids))
        relations = list(temporal_relations)
        evidence = list(evidence_refs)
        issues = self._issues(ids, relations, evidence)
        decision = self._decision(issues)
        review_id = stable_id("review-gate-3", timeline_run_id)
        route_id = stable_id("review-gate-3-route", timeline_run_id)
        result = ReviewGate3ResultV1(
            review_id=review_id,
            project_id=project_id,
            source_approved_proposal_bundle_id=source_approved_proposal_bundle_id,
            source_narrative_execution_bundle_id=source_narrative_execution_bundle_id,
            timeline_run_id=timeline_run_id,
            reviewer_agent_run_id=reviewer_agent_run_id,
            decision=decision,
            issues=issues,
            safe_summary=(
                "Timeline structure approved"
                if not issues
                else "Timeline review requires action"
            ),
            issue_count=len(issues),
            checked_event_ids=ids,
            checked_temporal_relation_ids=[relation.proposal_id for relation in relations],
            evidence_refs=evidence,
        )
        bundle = self.build_approved_bundle(
            decision=decision,
            route_id=route_id,
            review_id=review_id,
            project_id=project_id,
            source_bundle_id=source_approved_proposal_bundle_id,
            source_gate2_review_id=source_gate2_review_id,
            source_gate2_route_id=source_gate2_route_id,
            timeline_run_id=timeline_run_id,
            relations=relations,
            event_ids=ids,
            evidence=evidence,
        )
        route = NarrativeTimelineReviewRouteV1(
            route_id=route_id,
            review_id=review_id,
            timeline_run_id=timeline_run_id,
            route=decision,
            source_approved_proposal_bundle_id=source_approved_proposal_bundle_id,
            source_narrative_execution_bundle_id=source_narrative_execution_bundle_id,
            approved_timeline_bundle_id=bundle.bundle_id if bundle is not None else None,
            approved_timeline_bundle=bundle,
            held_issue_ids=(
                [issue.issue_id for issue in issues]
                if decision == ReviewGate3Decision.NEEDS_HUMAN_REVIEW
                else []
            ),
            safe_issue_codes=list(dict.fromkeys(issue.issue_code for issue in issues)),
        )
        return result, route

    def failed(
        self,
        *,
        project_id: str,
        source_approved_proposal_bundle_id: str | None,
        source_narrative_execution_bundle_id: str | None = None,
        timeline_run_id: str,
        reviewer_agent_run_id: str,
    ) -> tuple[ReviewGate3ResultV1, NarrativeTimelineReviewRouteV1]:
        """Persist a source-free failure route if deterministic review cannot execute."""

        review_id = stable_id("review-gate-3", timeline_run_id)
        route_id = stable_id("review-gate-3-route", timeline_run_id)
        issue = TimelineGate3IssueV1(
            issue_id=stable_id("gate3-issue", "review-execution", timeline_run_id),
            issue_code=TimelineGate3IssueCode.REVIEW_EXECUTION_FAILED,
            severity=TimelineGate3IssueSeverity.BLOCKING,
            recoverable=False,
            sanitized_message="Timeline review execution failed",
        )
        result = ReviewGate3ResultV1(
            review_id=review_id,
            project_id=project_id,
            source_approved_proposal_bundle_id=source_approved_proposal_bundle_id,
            source_narrative_execution_bundle_id=source_narrative_execution_bundle_id,
            timeline_run_id=timeline_run_id,
            reviewer_agent_run_id=reviewer_agent_run_id,
            decision=ReviewGate3Decision.FAILED,
            issues=[issue],
            safe_summary="Timeline review execution failed",
            issue_count=1,
        )
        return result, NarrativeTimelineReviewRouteV1(
            route_id=route_id,
            review_id=review_id,
            timeline_run_id=timeline_run_id,
            route=ReviewGate3Decision.FAILED,
            source_approved_proposal_bundle_id=source_approved_proposal_bundle_id,
            source_narrative_execution_bundle_id=source_narrative_execution_bundle_id,
            safe_issue_codes=[TimelineGate3IssueCode.REVIEW_EXECUTION_FAILED],
        )

    @staticmethod
    def _decision(issues: list[TimelineGate3IssueV1]) -> ReviewGate3Decision:
        if any(issue.severity == TimelineGate3IssueSeverity.BLOCKING for issue in issues):
            return ReviewGate3Decision.REJECTED
        if issues:
            return ReviewGate3Decision.NEEDS_HUMAN_REVIEW
        return ReviewGate3Decision.APPROVED

    @staticmethod
    def build_approved_bundle(
        *,
        decision: ReviewGate3Decision,
        route_id: str,
        review_id: str,
        project_id: str,
        source_bundle_id: str | None,
        source_gate2_review_id: str,
        source_gate2_route_id: str,
        timeline_run_id: str,
        relations: list[TemporalRelationProposalV1],
        event_ids: list[str],
        evidence: list[EvidenceRefV1],
    ) -> ApprovedTimelineBundleV1 | None:
        """Build the sole canonical approved Timeline artifact for either approval path."""

        if decision != ReviewGate3Decision.APPROVED or source_bundle_id is None:
            return None
        return ApprovedTimelineBundleV1(
            bundle_id=stable_id("approved-timeline", timeline_run_id, review_id),
            project_id=project_id,
            source_approved_proposal_bundle_id=source_bundle_id,
            source_gate2_review_id=source_gate2_review_id,
            source_gate2_route_id=source_gate2_route_id,
            timeline_run_id=timeline_run_id,
            gate3_review_id=review_id,
            gate3_route_id=route_id,
            temporal_relations=relations,
            event_ids=event_ids,
            evidence_refs=evidence,
        )

    def _issues(
        self,
        event_ids: list[str],
        relations: list[TemporalRelationProposalV1],
        evidence: list[EvidenceRefV1],
    ) -> list[TimelineGate3IssueV1]:
        known = set(event_ids)
        allowed = {
            (ref.chunk_id, ref.quote_start, ref.quote_end, ref.quote_text)
            for ref in evidence
        }
        issues: list[TimelineGate3IssueV1] = []
        graph: dict[str, set[str]] = defaultdict(set)
        pair_relation: dict[tuple[str, str], TemporalRelation] = {}
        for relation in relations:
            event_pair = [relation.source_event_id, relation.target_event_id]
            if not set(event_pair).issubset(known):
                issues.append(
                    self._issue(
                        TimelineGate3IssueCode.UNKNOWN_EVENT_REFERENCE,
                        TimelineGate3IssueSeverity.BLOCKING,
                        relation,
                        event_pair,
                    )
                )
                continue
            if any(
                (ref.chunk_id, ref.quote_start, ref.quote_end, ref.quote_text) not in allowed
                for ref in relation.evidence_refs
            ):
                issues.append(
                    self._issue(
                        TimelineGate3IssueCode.EVIDENCE_OUT_OF_SCOPE,
                        TimelineGate3IssueSeverity.BLOCKING,
                        relation,
                        event_pair,
                    )
                )
            key = (relation.source_event_id, relation.target_event_id)
            if key in pair_relation and pair_relation[key] != relation.relation:
                issues.append(
                    self._issue(
                        TimelineGate3IssueCode.CONFLICTING_RELATIONS,
                        TimelineGate3IssueSeverity.BLOCKING,
                        relation,
                        event_pair,
                    )
                )
            pair_relation[key] = relation.relation
            if relation.relation == TemporalRelation.BEFORE:
                graph[relation.source_event_id].add(relation.target_event_id)
            elif relation.relation == TemporalRelation.AFTER:
                graph[relation.target_event_id].add(relation.source_event_id)
            elif relation.relation == TemporalRelation.UNKNOWN:
                issues.append(
                    self._issue(
                        TimelineGate3IssueCode.AMBIGUOUS_ORDERING,
                        TimelineGate3IssueSeverity.REVIEW_REQUIRED,
                        relation,
                        event_pair,
                    )
                )
        if self._has_cycle(graph):
            issues.append(
                TimelineGate3IssueV1(
                    issue_id=stable_id("gate3-issue", "timeline-cycle"),
                    issue_code=TimelineGate3IssueCode.TEMPORAL_CYCLE,
                    severity=TimelineGate3IssueSeverity.BLOCKING,
                    related_event_ids=sorted(graph),
                    recoverable=True,
                    safe_recovery_action="rerun_with_same_approved_scope",
                    sanitized_message="Timeline structural check: TEMPORAL_CYCLE",
                )
            )
        return issues

    def _issue(
        self,
        code: TimelineGate3IssueCode,
        severity: TimelineGate3IssueSeverity,
        relation: TemporalRelationProposalV1,
        event_ids: list[str],
    ) -> TimelineGate3IssueV1:
        return TimelineGate3IssueV1(
            issue_id=stable_id("gate3-issue", code, relation.proposal_id),
            issue_code=code,
            severity=severity,
            related_event_ids=event_ids,
            related_relation_ids=[relation.proposal_id],
            evidence_refs=relation.evidence_refs,
            recoverable=code in self._RECOVERABLE,
            safe_recovery_action=(
                "rerun_with_same_approved_scope" if code in self._RECOVERABLE else None
            ),
            sanitized_message=f"Timeline structural check: {code.value}",
        )

    @staticmethod
    def _has_cycle(graph: dict[str, set[str]]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            found = any(visit(next_node) for next_node in graph.get(node, set()))
            visiting.remove(node)
            visited.add(node)
            return found

        return any(visit(node) for node in graph)
