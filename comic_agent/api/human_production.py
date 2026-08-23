"""Minimal HTTP wiring for the unified Human Review StoryBible production path."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.api.dependencies import (
    SessionDep,
    get_narrative_analysis_recovery_repository,
    get_narrative_analysis_repository,
    get_repository,
    get_timeline_gate3_repository,
)
from comic_agent.config import get_settings
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.human_review_repository import (
    HumanReviewRepository,
    RepositoryConflictError,
)
from comic_agent.repositories.production_dossier_repository import (
    ProductionDossierRepository,
)
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.human_review import HumanReviewResultV1, HumanReviewSubmissionV1
from comic_agent.schemas.storybible import (
    HumanApprovedStoryBibleProductionExecutionFailureCode,
    StoryBibleProductionAuthorizationFailureV1,
    StoryBibleProductionRunV1,
)
from comic_agent.services.human_approved_storybible_production_context import (
    DurableHumanApprovedStoryBibleProductionContextLoader,
)
from comic_agent.services.human_approved_storybible_production_execution_adapter import (
    HumanApprovedStoryBibleProductionExecutionAdapter,
)
from comic_agent.services.human_approved_storybible_production_service import (
    HumanApprovedStoryBibleProductionService,
)
from comic_agent.services.human_review_service import HumanReviewService
from comic_agent.services.production_dossier_materializer import ProductionDossierMaterializer
from comic_agent.services.storybible_production_context import StoryBibleProductionInputBuilder
from comic_agent.services.storybible_production_coordinator import (
    StoryBibleProductionCoordinator,
    StoryBibleProductionExecutionError,
)
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)

router = APIRouter(tags=["Human Review Production"])

SessionRepositoryDep = Annotated[SourceRepository, Depends(get_repository)]


def _materializer(session: SessionDep) -> ProductionDossierMaterializer:
    """Build the post-Gate-3 read model from repositories sharing one request session."""

    return ProductionDossierMaterializer(
        analysis_repository=get_narrative_analysis_repository(session),
        recovery_repository=get_narrative_analysis_recovery_repository(session),
        timeline_repository=get_timeline_gate3_repository(session),
        dossier_repository=ProductionDossierRepository(session),
    )


@router.get("/projects/{project_id}/pipeline-runs/{analysis_run_id}/production-dossiers")
def list_production_dossiers(
    project_id: str,
    analysis_run_id: str,
    session: SessionDep,
) -> dict[str, object]:
    """Expose identifiers and hashes for terminal, persisted Human Review material."""

    materializer = _materializer(session)
    try:
        dossiers = materializer.available_terminal(analysis_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Narrative analysis run not found") from exc
    if any(dossier.project_id != project_id for dossier in dossiers):
        raise HTTPException(status_code=404, detail="Production dossier not found")
    return {
        "project_id": project_id,
        "analysis_run_id": analysis_run_id,
        "dossiers": [
            {
                "dossier_id": dossier.dossier_id,
                "content_hash": ProductionDossierRepository(session).get_content_hash(
                    dossier.dossier_id
                ),
                "timeline_review_material_id": dossier.timeline_review_material_id,
            }
            for dossier in dossiers
        ],
    }


@router.post(
    "/projects/{project_id}/production-dossiers/{dossier_id}/human-review",
    response_model=HumanReviewResultV1,
)
def submit_human_review(
    project_id: str,
    dossier_id: str,
    submission: HumanReviewSubmissionV1,
    session: SessionDep,
) -> HumanReviewResultV1:
    """Record one insert-only unified human decision for a durable Dossier."""

    dossier_repository = ProductionDossierRepository(session)
    dossier = dossier_repository.get_by_dossier_id(dossier_id)
    if dossier is None or dossier.project_id != project_id:
        raise HTTPException(status_code=404, detail="Production dossier not found")
    if submission.project_id != project_id or submission.dossier_id != dossier_id:
        raise HTTPException(
            status_code=409, detail="Human review request lineage does not match path"
        )
    try:
        return HumanReviewService(
            HumanReviewRepository(session), dossier_repository
        ).review(dossier=dossier, submission=submission)
    except RepositoryConflictError as exc:
        raise HTTPException(
            status_code=409, detail="Human review decision conflicts with existing review"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Human review dossier is invalid") from exc


def _storybible_curator(request: Request) -> StoryBibleCurator:
    return cast(StoryBibleCurator, request.app.state.storybible_curator)


@router.post(
    "/projects/{project_id}/storybible-production/human-reviews/{human_review_id}/execute",
    response_model=None,
)
def execute_human_approved_storybible_production(
    project_id: str,
    human_review_id: str,
    request: Request,
    session: SessionDep,
    source_repository: SessionRepositoryDep,
    real_llm_requested: Annotated[bool, Query()] = False,
) -> StoryBibleProductionRunV1 | JSONResponse:
    """Execute StoryBible curation only after the durable human-approved adapter succeeds."""

    settings = get_settings()
    adapter = HumanApprovedStoryBibleProductionExecutionAdapter(
        StoryBibleProductionRunRepository(session),
        HumanReviewRepository(session),
        ProductionDossierRepository(session),
        DurableHumanApprovedStoryBibleProductionContextLoader(
            source_repository,
            StoryBibleRepository(session),
        ),
    )
    coordinator = StoryBibleProductionCoordinator(
        input_builder=StoryBibleProductionInputBuilder(session),
        run_repository=StoryBibleProductionRunRepository(session),
        curator=_storybible_curator(request),
        output_normalizer=StoryBibleProductionOutputNormalizer(),
        agent_run_repository=AgentRunRepository(session),
        settings=settings,
    )
    try:
        result = HumanApprovedStoryBibleProductionService(adapter, coordinator).execute(
            project_id=project_id,
            human_review_id=human_review_id,
            model_identity=settings.storybible_model,
            real_llm_requested=real_llm_requested,
        )
    except StoryBibleProductionExecutionError:
        return JSONResponse(
            status_code=409,
            content={
                "status": "NOT_EXECUTED",
                "failure_code": "STORYBIBLE_PRODUCTION_NOT_READY",
                "human_review_id": human_review_id,
            },
        )
    if isinstance(result, HumanApprovedStoryBibleProductionExecutionFailureCode):
        return JSONResponse(
            status_code=409,
            content={
                "status": "NOT_EXECUTED",
                "failure_code": str(result),
                "human_review_id": human_review_id,
            },
        )
    if isinstance(result, StoryBibleProductionAuthorizationFailureV1):
        return JSONResponse(
            status_code=409,
            content={
                "status": "NOT_EXECUTED",
                "failure_code": str(result.code),
                "human_review_id": human_review_id,
            },
        )
    return result
