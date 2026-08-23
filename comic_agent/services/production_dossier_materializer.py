"""Runtime materialization of Human Review dossiers from completed Gate 3 artifacts."""

from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.production_dossier_repository import ProductionDossierRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.review import NarrativeAnalysisReviewRouteV1
from comic_agent.schemas.storybible import ProductionDossierV1
from comic_agent.schemas.timeline import TimelineGate3RunStatus
from comic_agent.services.production_dossier_builder import ProductionDossierBuilder

_DOSSIER_ELIGIBLE_GATE3_STATUSES = {
    TimelineGate3RunStatus.APPROVED,
    TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
    TimelineGate3RunStatus.REJECTED,
}


class ProductionDossierMaterializer:
    """Persist one Dossier for each terminal, reviewable Gate 3 material.

    This service deliberately sits after Gate 3.  It does not alter Gate decisions,
    rerun a provider, or create dossiers for failed Timeline executions.
    """

    def __init__(
        self,
        *,
        analysis_repository: NarrativeAnalysisRepository,
        recovery_repository: NarrativeAnalysisRecoveryRepository,
        timeline_repository: TimelineGate3Repository,
        dossier_repository: ProductionDossierRepository,
        builder: ProductionDossierBuilder | None = None,
    ) -> None:
        self._analysis = analysis_repository
        self._recovery = recovery_repository
        self._timeline = timeline_repository
        self._dossiers = dossier_repository
        self._builder = builder or ProductionDossierBuilder()

    def materialize_terminal(self, analysis_run_id: str) -> list[ProductionDossierV1]:
        """Build and insert every available terminal Gate 3 dossier idempotently."""

        run = self._analysis.get_run(analysis_run_id)
        if run is None:
            raise ValueError("Narrative analysis run not found")
        dossiers: list[ProductionDossierV1] = []
        seen_execution_bundle_ids: set[str] = set()
        for route in self._execution_routes(analysis_run_id, run.review_gate2_route):
            execution = route.narrative_execution_bundle
            if execution is None or execution.bundle_id in seen_execution_bundle_ids:
                continue
            seen_execution_bundle_ids.add(execution.bundle_id)
            timeline_run = self._timeline.get_by_bundle(
                run.project_id, self._timeline_source_id(route)
            )
            if (
                timeline_run is None
                or timeline_run.status not in _DOSSIER_ELIGIBLE_GATE3_STATUSES
                or timeline_run.timeline_review_material is None
            ):
                continue
            dossier = self._builder.build(
                narrative=execution,
                timeline=timeline_run.timeline_review_material,
            )
            dossiers.append(self._dossiers.insert(dossier))
        return dossiers

    def available_terminal(self, analysis_run_id: str) -> list[ProductionDossierV1]:
        """Return already-persisted Dossiers for a pipeline run without writing."""

        run = self._analysis.get_run(analysis_run_id)
        if run is None:
            raise ValueError("Narrative analysis run not found")
        dossiers: list[ProductionDossierV1] = []
        seen_ids: set[str] = set()
        for route in self._execution_routes(analysis_run_id, run.review_gate2_route):
            execution = route.narrative_execution_bundle
            if execution is None:
                continue
            timeline_run = self._timeline.get_by_bundle(
                run.project_id, self._timeline_source_id(route)
            )
            material = timeline_run.timeline_review_material if timeline_run is not None else None
            if material is None:
                continue
            dossier = self._builder.build(narrative=execution, timeline=material)
            stored = self._dossiers.get_by_dossier_id(dossier.dossier_id)
            if stored is not None and stored.dossier_id not in seen_ids:
                dossiers.append(stored)
                seen_ids.add(stored.dossier_id)
        return dossiers

    def _execution_routes(
        self,
        analysis_run_id: str,
        root_route: NarrativeAnalysisReviewRouteV1 | None,
    ) -> list[NarrativeAnalysisReviewRouteV1]:
        routes = [root_route] if root_route is not None else []
        routes.extend(
            attempt.fresh_route
            for attempt in self._recovery.list_attempts(analysis_run_id)
            if attempt.fresh_route is not None
        )
        return routes

    @staticmethod
    def _timeline_source_id(route: NarrativeAnalysisReviewRouteV1) -> str:
        """Match the repository's legacy-approved or execution-only lookup key."""

        if route.approved_proposal_bundle is not None:
            return route.approved_proposal_bundle.bundle_id
        execution = route.narrative_execution_bundle
        if execution is None:
            raise ValueError("Narrative execution material is required")
        return execution.bundle_id
