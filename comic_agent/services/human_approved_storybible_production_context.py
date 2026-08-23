"""Build the human-authorized StoryBible production context without executing production."""

import json

from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.human_review import HumanReviewDecision, HumanReviewRunV1
from comic_agent.schemas.narrative import EntityProposalV1, EventProposalV1, StateChangeProposalV1
from comic_agent.schemas.review import NarrativeExecutionBundleV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    HumanApprovedStoryBibleProductionContextV1,
    ProductionDossierV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleProductionInputV2,
)
from comic_agent.schemas.timeline import TimelineReviewMaterialV1


class HumanApprovedStoryBibleProductionContextBuilder:
    """Validate the complete human-approved artifact boundary into a read-only context."""

    def build(
        self,
        *,
        production_input: StoryBibleProductionInputV2,
        dossier: ProductionDossierV1,
        narrative: NarrativeExecutionBundleV1,
        timeline: TimelineReviewMaterialV1,
        canonical_snapshot: StoryBibleCanonicalSnapshotV1,
        source_chunks: list[SourceChunkV1],
    ) -> HumanApprovedStoryBibleProductionContextV1:
        self._validate_lineage(production_input, dossier, narrative, timeline)
        evidence_refs = _unique_evidence(
            [
                *narrative.evidence_refs,
                *timeline.evidence_refs,
            ]
        )
        expected_chunk_ids = sorted({reference.chunk_id for reference in evidence_refs})
        if len({chunk.chunk_id for chunk in source_chunks}) != len(source_chunks):
            raise ValueError("source chunks must not contain duplicate chunk ids")
        chunks_by_id = {chunk.chunk_id: chunk for chunk in source_chunks}
        if set(chunks_by_id) != set(expected_chunk_ids):
            raise ValueError("source chunks must exactly cover human-approved evidence scope")
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in expected_chunk_ids]
        entities = []
        events = []
        state_changes = []
        for candidate in narrative.candidates:
            proposal = candidate.proposal
            if isinstance(proposal, EntityProposalV1):
                entities.append(proposal)
            elif isinstance(proposal, EventProposalV1):
                events.append(proposal)
            elif isinstance(proposal, StateChangeProposalV1):
                state_changes.append(proposal)
        return HumanApprovedStoryBibleProductionContextV1(
            project_id=production_input.project_id,
            human_review_id=production_input.human_review_id,
            human_review_decision=production_input.human_review_decision,
            reviewer_id=production_input.reviewer_id,
            review_time=production_input.review_time,
            dossier_id=production_input.dossier_id,
            narrative_execution_bundle_id=production_input.narrative_execution_bundle_id,
            timeline_review_material_id=production_input.timeline_review_material_id,
            narrative_analysis_run_id=production_input.dossier_provenance.narrative_analysis_run_id,
            timeline_run_id=timeline.timeline_run_id,
            human_approved_entities=sorted(entities, key=lambda item: item.proposal_id),
            human_approved_events=sorted(events, key=lambda item: item.proposal_id),
            human_approved_state_changes=sorted(state_changes, key=lambda item: item.proposal_id),
            human_approved_temporal_relations=sorted(
                timeline.temporal_relations, key=lambda item: item.proposal_id
            ),
            narrative_execution_status=narrative.status,
            narrative_issues=list(narrative.issues),
            excluded_items=list(narrative.excluded_items),
            failed_windows=list(narrative.failed_windows),
            timeline_review_status=timeline.review_status,
            timeline_issues=list(timeline.issues),
            evidence_refs=evidence_refs,
            source_chunk_ids=expected_chunk_ids,
            source_chunks=ordered_chunks,
            canonical_snapshot=canonical_snapshot,
        )

    def build_from_durable_dossier(
        self,
        *,
        review: HumanReviewRunV1,
        dossier: ProductionDossierV1,
        canonical_snapshot: StoryBibleCanonicalSnapshotV1,
        source_chunks: list[SourceChunkV1],
    ) -> HumanApprovedStoryBibleProductionContextV1:
        """Build only from the persisted dossier approved by the stored review."""

        narrative = dossier.narrative_summary
        timeline = dossier.timeline_summary
        if dossier.schema_version != "1.2" or narrative is None or timeline is None:
            raise ValueError("durable human production requires a complete 1.2 dossier")
        if review.decision != HumanReviewDecision.APPROVE:
            raise ValueError("only an APPROVE review can build production context")
        if (
            review.project_id != dossier.project_id
            or review.dossier_id != dossier.dossier_id
            or review.lineage.narrative_execution_bundle_id
            != dossier.narrative_execution_bundle_id
            or review.lineage.timeline_review_material_id != dossier.timeline_review_material_id
        ):
            raise ValueError("persisted human review lineage does not match dossier")
        evidence_refs = _unique_evidence(list(dossier.evidence_refs))
        expected_chunk_ids = sorted({reference.chunk_id for reference in evidence_refs})
        if len({chunk.chunk_id for chunk in source_chunks}) != len(source_chunks):
            raise ValueError("source chunks must not contain duplicate chunk ids")
        chunks_by_id = {chunk.chunk_id: chunk for chunk in source_chunks}
        if set(chunks_by_id) != set(expected_chunk_ids):
            raise ValueError("source chunks must exactly cover durable dossier evidence scope")
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in expected_chunk_ids]
        entities = []
        events = []
        state_changes = []
        for candidate in narrative.candidates:
            proposal = candidate.proposal
            if isinstance(proposal, EntityProposalV1):
                entities.append(proposal)
            elif isinstance(proposal, EventProposalV1):
                events.append(proposal)
            elif isinstance(proposal, StateChangeProposalV1):
                state_changes.append(proposal)
        return HumanApprovedStoryBibleProductionContextV1(
            project_id=dossier.project_id,
            human_review_id=review.review_id,
            human_review_decision="APPROVE",
            reviewer_id=review.reviewer_id,
            review_time=review.created_at,
            dossier_id=dossier.dossier_id,
            narrative_execution_bundle_id=dossier.narrative_execution_bundle_id,
            timeline_review_material_id=dossier.timeline_review_material_id,
            narrative_analysis_run_id=dossier.provenance.narrative_analysis_run_id,
            timeline_run_id=dossier.provenance.timeline_run_id or "missing-timeline-run",
            human_approved_entities=sorted(entities, key=lambda item: item.proposal_id),
            human_approved_events=sorted(events, key=lambda item: item.proposal_id),
            human_approved_state_changes=sorted(state_changes, key=lambda item: item.proposal_id),
            human_approved_temporal_relations=sorted(
                timeline.temporal_relations, key=lambda item: item.proposal_id
            ),
            narrative_execution_status=narrative.execution_status,
            narrative_issues=list(narrative.issues),
            excluded_items=list(narrative.excluded_items),
            failed_windows=list(narrative.failed_windows),
            timeline_review_status=timeline.review_status,
            timeline_issues=list(timeline.issues),
            evidence_refs=evidence_refs,
            source_chunk_ids=expected_chunk_ids,
            source_chunks=ordered_chunks,
            canonical_snapshot=canonical_snapshot,
        )

    @staticmethod
    def _validate_lineage(
        production_input: StoryBibleProductionInputV2,
        dossier: ProductionDossierV1,
        narrative: NarrativeExecutionBundleV1,
        timeline: TimelineReviewMaterialV1,
    ) -> None:
        project_ids = {
            production_input.project_id,
            dossier.project_id,
            narrative.project_id,
            timeline.project_id,
        }
        if len(project_ids) != 1:
            raise ValueError("human-approved artifacts must belong to one project")
        if (
            production_input.dossier_id != dossier.dossier_id
            or production_input.narrative_execution_bundle_id != narrative.bundle_id
            or production_input.timeline_review_material_id != timeline.material_id
            or production_input.dossier_provenance != dossier.provenance
            or production_input.evidence_refs != dossier.evidence_refs
            or timeline.narrative_execution_bundle_id != narrative.bundle_id
            or narrative.provenance.analysis_run_id
            != production_input.dossier_provenance.narrative_analysis_run_id
            or narrative.provenance.gate1_review_id
            != production_input.dossier_provenance.gate1_review_id
            or timeline.timeline_run_id != production_input.dossier_provenance.timeline_run_id
        ):
            raise ValueError("human-approved production lineage does not match supplied artifacts")


def _unique_evidence(values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
    keyed: dict[str, EvidenceRefV1] = {}
    for value in values:
        payload = value.model_dump(mode="json")
        keyed[json.dumps(payload, ensure_ascii=False, sort_keys=True)] = value
    return [keyed[key] for key in sorted(keyed)]


class DurableHumanApprovedStoryBibleProductionContextLoader:
    """Load source and canonical context by project; never accept caller material."""

    def __init__(
        self,
        source_repository: SourceRepository,
        storybible_repository: StoryBibleRepository,
        builder: HumanApprovedStoryBibleProductionContextBuilder | None = None,
    ) -> None:
        self._sources = source_repository
        self._storybible = storybible_repository
        self._builder = builder or HumanApprovedStoryBibleProductionContextBuilder()

    def load(
        self, *, review: HumanReviewRunV1, dossier: ProductionDossierV1
    ) -> HumanApprovedStoryBibleProductionContextV1:
        source_chunks = []
        for chunk_id in sorted({ref.chunk_id for ref in dossier.evidence_refs}):
            chunk = self._sources.get_chunk(chunk_id)
            if chunk is None or chunk.project_id != dossier.project_id:
                raise ValueError("durable dossier source scope is unavailable")
            source_chunks.append(chunk)
        snapshot = StoryBibleCanonicalSnapshotV1(
            project_id=dossier.project_id,
            profiles=self._storybible.list_profiles(dossier.project_id),
            states=self._storybible.list_states(dossier.project_id),
            relationships=self._storybible.list_relationships(dossier.project_id),
            world_rules=self._storybible.list_world_rules(dossier.project_id),
        )
        return self._builder.build_from_durable_dossier(
            review=review,
            dossier=dossier,
            canonical_snapshot=snapshot,
            source_chunks=source_chunks,
        )
