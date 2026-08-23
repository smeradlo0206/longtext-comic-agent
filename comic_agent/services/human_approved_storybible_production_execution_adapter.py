"""Prepare human-approved StoryBible material for the existing execution coordinator."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from comic_agent.repositories.human_review_repository import HumanReviewRepository
from comic_agent.repositories.production_dossier_repository import ProductionDossierRepository
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.schemas.human_review import HumanReviewRunV1
from comic_agent.schemas.storybible import (
    HumanApprovedStoryBibleProductionContextV1,
    HumanApprovedStoryBibleProductionExecutionFailureCode,
    HumanApprovedStoryBibleProductionLineageV1,
    ProductionDossierV1,
    StoryBibleProductionAuthorizationKind,
    StoryBibleProductionContextV1,
    StoryBibleProductionInputV1,
    StoryBibleProductionRunV1,
)
from comic_agent.services.human_approved_storybible_production_context import (
    DurableHumanApprovedStoryBibleProductionContextLoader,
)
from comic_agent.services.production_dossier_identity import production_dossier_content_hash
from comic_agent.services.storybible_production_context import (
    PreparedStoryBibleProduction,
    canonical_storybible_snapshot_hash,
    derive_storybible_trusted_event_order,
)


@dataclass(frozen=True)
class HumanApprovedStoryBibleProductionExecutionResult:
    """Structured pre-execution result; a business rejection never raises."""

    prepared: PreparedStoryBibleProduction | None = None
    failure_code: HumanApprovedStoryBibleProductionExecutionFailureCode | None = None

    def __post_init__(self) -> None:
        if (self.prepared is None) == (self.failure_code is None):
            raise ValueError("execution result requires exactly one outcome")


class HumanContextValidationError(ValueError):
    """The supplied human-approved boundary artifact is structurally invalid."""


class ProductionReservationError(RuntimeError):
    """The trusted context was valid but its production reservation failed."""


class RepositoryConflictError(ProductionReservationError):
    """A durable repository rejected a conflicting human-approved reservation."""


class HumanApprovedContextLoader(Protocol):
    """Server-owned material loader; callers never supply a production context."""

    def load(
        self, *, review: HumanReviewRunV1, dossier: ProductionDossierV1
    ) -> HumanApprovedStoryBibleProductionContextV1: ...


class HumanApprovedStoryBibleProductionExecutionAdapter:
    """Adapt validated human-approved material without re-running upstream stages."""

    def __init__(
        self,
        run_repository: StoryBibleProductionRunRepository,
        human_review_repository: HumanReviewRepository,
        dossier_repository: ProductionDossierRepository,
        context_loader: DurableHumanApprovedStoryBibleProductionContextLoader,
    ) -> None:
        self._runs = run_repository
        self._human_reviews = human_review_repository
        self._dossiers = dossier_repository
        self._context_loader = context_loader

    def build_and_reserve(
        self,
        *,
        project_id: str,
        human_review_id: str,
        model_identity: str,
    ) -> HumanApprovedStoryBibleProductionExecutionResult:
        review = self._human_reviews.get_by_review_id(human_review_id)
        if review is None or review.project_id != project_id or str(review.decision) != "APPROVE":
            return HumanApprovedStoryBibleProductionExecutionResult(
                failure_code=(
                    HumanApprovedStoryBibleProductionExecutionFailureCode.HUMAN_REVIEW_NOT_APPROVED
                )
            )
        try:
            dossier = self._dossiers.get_by_dossier_id(review.dossier_id)
            if dossier is None or dossier.project_id != project_id:
                raise HumanContextValidationError("approved dossier was not found")
            if review.dossier_hash != production_dossier_content_hash(dossier):
                raise HumanContextValidationError("approved dossier hash does not match")
            context = self._context_loader.load(review=review, dossier=dossier)
            validated = HumanApprovedStoryBibleProductionContextV1.model_validate(
                context.model_dump()
            )
            self._validate_persisted_human_review(validated, review)
            production_input, execution_context = self._build_execution_material(validated)
        except (ValidationError, HumanContextValidationError, ValueError):
            return HumanApprovedStoryBibleProductionExecutionResult(
                failure_code=(
                    HumanApprovedStoryBibleProductionExecutionFailureCode.INVALID_HUMAN_APPROVED_CONTEXT
                )
            )
        try:
            run = self._reserve(production_input, model_identity=model_identity)
        except RepositoryConflictError:
            return HumanApprovedStoryBibleProductionExecutionResult(
                failure_code=(
                    HumanApprovedStoryBibleProductionExecutionFailureCode.REPOSITORY_CONFLICT
                )
            )
        except ProductionReservationError:
            return HumanApprovedStoryBibleProductionExecutionResult(
                failure_code=(
                    HumanApprovedStoryBibleProductionExecutionFailureCode.PRODUCTION_RESERVATION_FAILED
                )
            )
        return HumanApprovedStoryBibleProductionExecutionResult(
            prepared=PreparedStoryBibleProduction(
                production_input=production_input,
                context=execution_context,
                run=run,
            )
        )

    def _validate_persisted_human_review(
        self, context: HumanApprovedStoryBibleProductionContextV1, review: HumanReviewRunV1
    ) -> None:
        if (
            review.project_id != context.project_id
            or review.dossier_id != context.dossier_id
            or str(review.decision) != context.human_review_decision
            or review.reviewer_id != context.reviewer_id
            or review.created_at != context.review_time
            or review.lineage.narrative_execution_bundle_id != context.narrative_execution_bundle_id
            or review.lineage.timeline_review_material_id != context.timeline_review_material_id
        ):
            raise HumanContextValidationError(
                "human review authorization lineage does not match context"
            )

    def _build_execution_material(
        self,
        context: HumanApprovedStoryBibleProductionContextV1,
    ) -> tuple[StoryBibleProductionInputV1, StoryBibleProductionContextV1]:
        lineage = HumanApprovedStoryBibleProductionLineageV1(
            human_review_id=context.human_review_id,
            dossier_id=context.dossier_id,
            narrative_execution_bundle_id=context.narrative_execution_bundle_id,
            timeline_review_material_id=context.timeline_review_material_id,
        )
        snapshot_hash = canonical_storybible_snapshot_hash(context.canonical_snapshot)
        try:
            production_input = StoryBibleProductionInputV1(
                schema_version="1.2",
                project_id=context.project_id,
                human_review_id=lineage.human_review_id,
                production_dossier_id=lineage.dossier_id,
                narrative_execution_bundle_id=lineage.narrative_execution_bundle_id,
                timeline_review_material_id=lineage.timeline_review_material_id,
                canonical_storybible_snapshot_hash=snapshot_hash,
                authorization_kind=StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
                human_approved_lineage=lineage,
            )
            events = sorted(context.human_approved_events, key=lambda value: value.proposal_id)
            execution_context = StoryBibleProductionContextV1(
                schema_version="1.2",
                project_id=context.project_id,
                narrative_analysis_run_id=context.narrative_analysis_run_id,
                timeline_run_id=context.timeline_run_id,
                human_review_id=lineage.human_review_id,
                production_dossier_id=lineage.dossier_id,
                narrative_execution_bundle_id=lineage.narrative_execution_bundle_id,
                timeline_review_material_id=lineage.timeline_review_material_id,
                approved_entities=sorted(
                    context.human_approved_entities, key=lambda value: value.proposal_id
                ),
                approved_events=events,
                approved_state_changes=sorted(
                    context.human_approved_state_changes, key=lambda value: value.proposal_id
                ),
                approved_temporal_relations=sorted(
                    context.human_approved_temporal_relations,
                    key=lambda value: value.proposal_id,
                ),
                trusted_event_ids=[value.proposal_id for value in events],
                trusted_event_order=derive_storybible_trusted_event_order(
                    [value.proposal_id for value in events],
                    context.human_approved_temporal_relations,
                ),
                trusted_evidence_refs=list(context.evidence_refs),
                source_chunk_ids=list(context.source_chunk_ids),
                source_chunks=list(context.source_chunks),
                canonical_snapshot=context.canonical_snapshot,
                canonical_storybible_snapshot_hash=snapshot_hash,
                authorization_kind=StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
                human_approved_lineage=lineage,
            )
        except (ValidationError, ValueError) as exc:
            raise HumanContextValidationError("human-approved context has invalid lineage") from exc
        return production_input, execution_context

    def _reserve(
        self, production_input: StoryBibleProductionInputV1, *, model_identity: str
    ) -> StoryBibleProductionRunV1:
        lineage = production_input.human_approved_lineage
        if lineage is None:  # defensive: construction above establishes this invariant.
            raise HumanContextValidationError("human-approved production input lacks lineage")
        try:
            return self._runs.reserve_human_approved_run(
                production_input,
                lineage=lineage,
                model_identity=model_identity,
            )
        except ValueError as exc:
            raise RepositoryConflictError(
                "human-approved production reservation was rejected"
            ) from exc
        except Exception as exc:
            raise ProductionReservationError(
                "human-approved production reservation failed"
            ) from exc
