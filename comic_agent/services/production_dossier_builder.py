"""Pure aggregation of audited Narrative and Timeline material for human review."""

from __future__ import annotations

from comic_agent.schemas import EvidenceRefV1, NarrativeExecutionBundleV1, TimelineReviewMaterialV1
from comic_agent.schemas.review import ReviewIssueCategory
from comic_agent.schemas.storybible import (
    ProductionDossierIssueProvenanceV1,
    ProductionDossierIssueStage,
    ProductionDossierIssueV1,
    ProductionDossierNarrativeSummaryV1,
    ProductionDossierProvenanceV1,
    ProductionDossierTimelineSummaryV1,
    ProductionDossierV1,
)
from comic_agent.services.id_service import stable_id


class ProductionDossierBuilder:
    """Build one non-canonical dossier without executing or persisting anything."""

    def build(
        self,
        *,
        narrative: NarrativeExecutionBundleV1,
        timeline: TimelineReviewMaterialV1,
    ) -> ProductionDossierV1:
        self._validate_inputs(narrative=narrative, timeline=timeline)
        evidence_refs = _unique_evidence(
            [
                *narrative.evidence_refs,
                *timeline.evidence_refs,
            ]
        )
        unified_issues = [
            *self._narrative_issues(narrative=narrative),
            *self._timeline_issues(narrative=narrative, timeline=timeline),
        ]
        evidence_refs = _unique_evidence(
            [
                *evidence_refs,
                *(ref for issue in unified_issues for ref in issue.evidence_refs),
            ]
        )
        return ProductionDossierV1(
            dossier_id=stable_id("production-dossier", narrative.bundle_id, timeline.material_id),
            project_id=narrative.project_id,
            document_id=narrative.document_id,
            narrative_execution_bundle_id=narrative.bundle_id,
            timeline_review_material_id=timeline.material_id,
            gate2_findings=list(narrative.issues),
            gate3_findings=list(timeline.issues),
            evidence_refs=evidence_refs,
            narrative_summary=ProductionDossierNarrativeSummaryV1(
                execution_status=narrative.status,
                candidates=list(narrative.candidates),
                failed_windows=list(narrative.failed_windows),
                excluded_items=list(narrative.excluded_items),
                issues=list(narrative.issues),
                evidence_refs=list(narrative.evidence_refs),
            ),
            timeline_summary=ProductionDossierTimelineSummaryV1(
                timeline_candidate=timeline.timeline_candidate,
                temporal_relations=list(timeline.temporal_relations),
                review_status=timeline.review_status,
                issues=list(timeline.issues),
                evidence_refs=list(timeline.evidence_refs),
            ),
            unified_issues=unified_issues,
            provenance=ProductionDossierProvenanceV1(
                narrative_analysis_run_id=narrative.provenance.analysis_run_id,
                gate1_review_id=narrative.provenance.gate1_review_id,
                gate2_review_run_id=narrative.provenance.gate2_review_run_id,
                gate3_review_id=timeline.review_id,
                timeline_run_id=timeline.timeline_run_id,
                timeline_agent_run_id=timeline.provenance.timeline_agent_run_id,
                gate3_reviewer_agent_run_id=timeline.provenance.gate3_reviewer_agent_run_id,
                source_chunk_ids=_unique_strings(
                    [*narrative.provenance.source_chunk_ids, *timeline.provenance.source_chunk_ids]
                ),
            ),
        )

    @staticmethod
    def _validate_inputs(
        *, narrative: NarrativeExecutionBundleV1, timeline: TimelineReviewMaterialV1
    ) -> None:
        if narrative.project_id != timeline.project_id:
            raise ValueError("Narrative bundle and Timeline material must belong to one project")
        if timeline.narrative_execution_bundle_id != narrative.bundle_id:
            raise ValueError(
                "Timeline material must reference the supplied Narrative execution bundle"
            )
        event_ids = {
            candidate.proposal.proposal_id
            for candidate in narrative.candidates
            if candidate.proposal_schema == "EventProposalV1"
        }
        relation_event_ids = {
            event_id
            for relation in timeline.temporal_relations
            for event_id in (relation.source_event_id, relation.target_event_id)
        }
        if not relation_event_ids.issubset(event_ids):
            raise ValueError(
                "Timeline event references must come from Narrative execution candidates"
            )

    @staticmethod
    def _narrative_issues(
        *, narrative: NarrativeExecutionBundleV1
    ) -> list[ProductionDossierIssueV1]:
        result: list[ProductionDossierIssueV1] = []
        for issue in narrative.issues:
            stage = (
                ProductionDossierIssueStage.EXECUTION
                if issue.category == ReviewIssueCategory.EXECUTION
                else ProductionDossierIssueStage.GATE2
            )
            result.append(
                ProductionDossierIssueV1(
                    issue_id=issue.issue_id,
                    source_issue_id=issue.issue_id,
                    source_stage=stage,
                    severity=str(issue.severity),
                    evidence_refs=[],
                    provenance=ProductionDossierIssueProvenanceV1(
                        narrative_execution_bundle_id=narrative.bundle_id,
                        narrative_analysis_run_id=narrative.provenance.analysis_run_id,
                        related_object_ids=list(issue.related_object_ids),
                    ),
                )
            )
        for window in narrative.failed_windows:
            result.append(
                ProductionDossierIssueV1(
                    issue_id=stable_id(
                        "dossier-execution-window", narrative.bundle_id, window.analysis_window_id
                    ),
                    source_stage=ProductionDossierIssueStage.EXECUTION,
                    severity="REVIEW_REQUIRED",
                    evidence_refs=[],
                    provenance=ProductionDossierIssueProvenanceV1(
                        narrative_execution_bundle_id=narrative.bundle_id,
                        narrative_analysis_run_id=narrative.provenance.analysis_run_id,
                        related_object_ids=[window.analysis_window_id],
                    ),
                )
            )
        return result

    @staticmethod
    def _timeline_issues(
        *, narrative: NarrativeExecutionBundleV1, timeline: TimelineReviewMaterialV1
    ) -> list[ProductionDossierIssueV1]:
        return [
            ProductionDossierIssueV1(
                issue_id=issue.issue_id,
                source_issue_id=issue.issue_id,
                source_stage=ProductionDossierIssueStage.GATE3,
                severity=str(issue.severity),
                evidence_refs=list(issue.evidence_refs),
                provenance=ProductionDossierIssueProvenanceV1(
                    narrative_execution_bundle_id=narrative.bundle_id,
                    timeline_review_material_id=timeline.material_id,
                    narrative_analysis_run_id=narrative.provenance.analysis_run_id,
                    timeline_run_id=timeline.timeline_run_id,
                    related_object_ids=[*issue.related_event_ids, *issue.related_relation_ids],
                ),
            )
            for issue in timeline.issues
        ]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _unique_evidence(values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
    result: list[EvidenceRefV1] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
