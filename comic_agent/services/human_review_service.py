"""Single human decision service over a fully assembled ProductionDossier."""

from comic_agent.repositories.human_review_repository import HumanReviewRepository
from comic_agent.repositories.production_dossier_repository import ProductionDossierRepository
from comic_agent.schemas.human_review import (
    HumanReviewResultStatus,
    HumanReviewResultV1,
    HumanReviewRunV1,
    HumanReviewSubmissionV1,
)
from comic_agent.schemas.storybible import ProductionDossierV1
from comic_agent.services.id_service import stable_id
from comic_agent.services.production_dossier_identity import production_dossier_content_hash


class HumanReviewService:
    """Records a human decision without executing or modifying downstream production."""

    def __init__(
        self,
        repository: HumanReviewRepository,
        dossier_repository: ProductionDossierRepository,
    ) -> None:
        self._repository = repository
        self._dossiers = dossier_repository

    def review(
        self, *, dossier: ProductionDossierV1, submission: HumanReviewSubmissionV1
    ) -> HumanReviewResultV1:
        self._validate_dossier(dossier)
        if (
            submission.project_id != dossier.project_id
            or submission.dossier_id != dossier.dossier_id
        ):
            raise ValueError(
                "human review submission must match the ProductionDossier project and id"
            )
        stored_dossier = self._dossiers.insert(dossier)
        dossier_hash = production_dossier_content_hash(stored_dossier)
        run = HumanReviewRunV1(
            review_id=stable_id("human-production-review", dossier.dossier_id, submission.decision),
            project_id=dossier.project_id,
            dossier_id=dossier.dossier_id,
            dossier_hash=dossier_hash,
            decision=submission.decision,
            reviewer_id=submission.reviewer_id,
            reviewer_note=submission.reviewer_note,
            lineage={
                "source_dossier_id": dossier.dossier_id,
                "narrative_execution_bundle_id": dossier.narrative_execution_bundle_id,
                "timeline_review_material_id": dossier.timeline_review_material_id,
            },
        )
        stored = self._repository.insert(run)
        return HumanReviewResultV1(
            review_run=stored,
            status={
                "APPROVE": HumanReviewResultStatus.READY_FOR_STORYBIBLE,
                "REJECT": HumanReviewResultStatus.REJECTED_BY_HUMAN,
                "REQUEST_CHANGES": HumanReviewResultStatus.NEEDS_REVISION,
            }[stored.decision],
        )

    @staticmethod
    def _validate_dossier(dossier: ProductionDossierV1) -> None:
        if (
            dossier.schema_version != "1.2"
            or dossier.narrative_summary is None
            or dossier.timeline_summary is None
        ):
            raise ValueError("human review requires a complete 1.2 ProductionDossier lineage")
        if (
            not dossier.provenance.narrative_analysis_run_id
            or not dossier.provenance.timeline_run_id
        ):
            raise ValueError("ProductionDossier lineage is incomplete")
