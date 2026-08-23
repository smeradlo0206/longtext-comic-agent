"""Non-executing handoff from a completed StoryBible production run to Comic Planning."""

from comic_agent.schemas.storybible import (
    ComicPlanningInputV1,
    StoryBibleProductionAuthorizationKind,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
)


class ComicPlanningInputAdapter:
    """Expose a typed handoff without starting Scene or panel planning."""

    def build(self, production_run: StoryBibleProductionRunV1) -> ComicPlanningInputV1:
        if (
            production_run.status != StoryBibleProductionRunStatus.SUCCEEDED
            or production_run.authorization_kind
            != StoryBibleProductionAuthorizationKind.HUMAN_APPROVED
            or production_run.curator_proposal is None
            or production_run.human_review_id is None
            or production_run.production_dossier_id is None
        ):
            raise ValueError("Comic Planning requires a completed human-approved production run")
        return ComicPlanningInputV1(
            project_id=production_run.project_id,
            storybible_production_run_id=production_run.run_id,
            human_review_id=production_run.human_review_id,
            production_dossier_id=production_run.production_dossier_id,
            canonical_storybible_snapshot_hash=(
                production_run.canonical_storybible_snapshot_hash
            ),
            curator_proposal_id=production_run.curator_proposal.proposal_id,
            evidence_refs=list(production_run.curator_proposal.evidence_refs),
        )
