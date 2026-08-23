"""Pure contract adapter from a human-approved dossier to future production input V2."""

from comic_agent.schemas.human_review import HumanReviewDecision, HumanReviewResultV1
from comic_agent.schemas.storybible import (
    ProductionDossierV1,
    StoryBibleProductionInputBuildResultV1,
    StoryBibleProductionInputFailureCode,
    StoryBibleProductionInputV2,
)
from comic_agent.services.production_dossier_identity import production_dossier_content_hash


class HumanApprovedStoryBibleInputBuilder:
    """Build only an input artifact; it never invokes a curator or coordinator."""

    def build(
        self, *, dossier: ProductionDossierV1, review: HumanReviewResultV1
    ) -> StoryBibleProductionInputBuildResultV1:
        run = review.review_run
        if run.decision != HumanReviewDecision.APPROVE:
            return StoryBibleProductionInputBuildResultV1(
                failure_code=StoryBibleProductionInputFailureCode.HUMAN_REVIEW_NOT_APPROVED
            )
        if run.project_id != dossier.project_id:
            return StoryBibleProductionInputBuildResultV1(
                failure_code=StoryBibleProductionInputFailureCode.PROJECT_MISMATCH
            )
        if run.dossier_hash != production_dossier_content_hash(dossier):
            return StoryBibleProductionInputBuildResultV1(
                failure_code=StoryBibleProductionInputFailureCode.LINEAGE_MISMATCH
            )
        if (
            run.dossier_id != dossier.dossier_id
            or run.lineage.source_dossier_id != dossier.dossier_id
            or run.lineage.narrative_execution_bundle_id
            != dossier.narrative_execution_bundle_id
            or run.lineage.timeline_review_material_id != dossier.timeline_review_material_id
        ):
            return StoryBibleProductionInputBuildResultV1(
                failure_code=StoryBibleProductionInputFailureCode.LINEAGE_MISMATCH
            )
        if (
            dossier.schema_version != "1.2"
            or dossier.narrative_summary is None
            or dossier.timeline_summary is None
            or not dossier.provenance.narrative_analysis_run_id
            or not dossier.provenance.timeline_run_id
        ):
            return StoryBibleProductionInputBuildResultV1(
                failure_code=StoryBibleProductionInputFailureCode.INVALID_DOSSIER_LINEAGE
            )
        return StoryBibleProductionInputBuildResultV1(
            production_input=StoryBibleProductionInputV2(
                project_id=dossier.project_id,
                human_review_id=run.review_id,
                human_review_decision="APPROVE",
                reviewer_id=run.reviewer_id,
                review_time=run.created_at,
                dossier_id=dossier.dossier_id,
                narrative_execution_bundle_id=dossier.narrative_execution_bundle_id,
                timeline_review_material_id=dossier.timeline_review_material_id,
                evidence_refs=list(dossier.evidence_refs),
                dossier_provenance=dossier.provenance,
            )
        )
