"""Bounded StoryBible curation, approval, and resource routes."""

from collections.abc import Iterator
from typing import Annotated, cast

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.api.dependencies import get_repository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    StoryBibleContextV1,
    StoryBibleCuratorProposalV1,
    StoryBibleSnapshotV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
)
from comic_agent.services.commit_service import CommitService
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.storybible_content_hash import with_computed_content_hash
from comic_agent.services.storybible_snapshot import build_state_snapshot
from comic_agent.services.storybible_validator import StoryBibleValidator

router = APIRouter()


def get_storybible_repository(request: Request) -> Iterator[StoryBibleRepository]:
    """Yield a StoryBible repository and close its request-local session."""

    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield StoryBibleRepository(session)
    finally:
        session.close()


def get_storybible_curator(request: Request) -> StoryBibleCurator:
    """Return the app-configured curator without coupling routes to a provider."""

    return cast(StoryBibleCurator, request.app.state.storybible_curator)


StoryBibleRepositoryDep = Annotated[
    StoryBibleRepository, Depends(get_storybible_repository)
]
SourceRepositoryDep = Annotated[SourceRepository, Depends(get_repository)]
StoryBibleCuratorDep = Annotated[StoryBibleCurator, Depends(get_storybible_curator)]
ApprovalStatusBody = Annotated[RecordStatus, Body(embed=True, alias="status")]
EventIdQuery = Annotated[str | None, Query(min_length=1)]
EventOrderQuery = Annotated[int, Query(ge=0)]


def _require_project_context(
    context: StoryBibleContextV1,
    project_id: str,
    source_repository: SourceRepository,
) -> None:
    """Reject nested resources or evidence outside the path project."""

    if context.project_id != project_id:
        raise HTTPException(status_code=409, detail="StoryBible context project mismatch")

    has_foreign_resource = (
        any(profile.project_id != project_id for profile in context.profiles)
        or any(state.project_id != project_id for state in context.states)
        or any(
            relationship.project_id != project_id
            for relationship in context.relationships
        )
        or any(rule.project_id != project_id for rule in context.world_rules)
    )
    if has_foreign_resource:
        raise HTTPException(status_code=409, detail="StoryBible context project mismatch")

    for chunk_id in context.source_chunk_ids:
        chunk = source_repository.get_chunk(chunk_id)
        if chunk is None or chunk.project_id != project_id:
            raise HTTPException(status_code=409, detail="StoryBible context project mismatch")

    evidence_groups = [
        *(proposal.evidence_refs for proposal in context.entity_proposals),
        *(proposal.evidence_refs for proposal in context.event_proposals),
        *(proposal.evidence_refs for proposal in context.claim_proposals),
        *(proposal.evidence_refs for proposal in context.state_change_proposals),
        *(proposal.evidence_refs for proposal in context.temporal_relation_proposals),
        *(profile.evidence_refs for profile in context.profiles),
        *(state.evidence_refs for state in context.states),
        *(relationship.evidence_refs for relationship in context.relationships),
        *(rule.evidence_refs for rule in context.world_rules),
    ]
    for evidence_refs in evidence_groups:
        _require_project_evidence(evidence_refs, project_id, source_repository)


def _build_project_context(
    requested_context: StoryBibleContextV1,
    project_id: str,
    repository: StoryBibleRepository,
    source_repository: SourceRepository,
) -> tuple[StoryBibleContextV1, dict[str, str]]:
    """Rebuild a bounded agent input from project-scoped canonical queries.

    Returns the StoryBible context and a dict mapping chunk IDs to their text.
    """

    _require_project_context(requested_context, project_id, source_repository)
    source_chunks = [
        source_repository.get_chunk(chunk_id)
        for chunk_id in requested_context.source_chunk_ids
    ]
    if any(chunk is None for chunk in source_chunks):  # pragma: no cover - checked above
        raise HTTPException(status_code=409, detail="StoryBible context project mismatch")
    resolved_chunks = [chunk for chunk in source_chunks if chunk is not None]
    chunk_texts = {chunk.chunk_id: chunk.text for chunk in resolved_chunks}
    try:
        return (
            ContextBuilder().storybible_context(
                project_id=project_id,
                profile_ids=(profile.profile_id for profile in requested_context.profiles),
                source_chunks=resolved_chunks,
                repository=repository,
                entity_proposals=requested_context.entity_proposals,
                event_proposals=requested_context.event_proposals,
                claim_proposals=requested_context.claim_proposals,
                state_change_proposals=requested_context.state_change_proposals,
                temporal_relation_proposals=requested_context.temporal_relation_proposals,
                world_rules=repository.list_world_rules(project_id),
            ),
            chunk_texts,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _require_project_evidence(
    evidence_refs: list[EvidenceRefV1],
    project_id: str,
    source_repository: SourceRepository,
) -> None:
    """Reject evidence that is missing or owned by another project."""

    for evidence_ref in evidence_refs:
        chunk = source_repository.get_chunk(evidence_ref.chunk_id)
        if chunk is None or chunk.project_id != project_id:
            raise HTTPException(status_code=409, detail="StoryBible context project mismatch")


@router.post(
    "/projects/{project_id}/storybible/curate",
    response_model=StoryBibleCuratorProposalV1,
)
def curate_storybible(
    project_id: str,
    context: StoryBibleContextV1,
    curator: StoryBibleCuratorDep,
    repository: StoryBibleRepositoryDep,
    source_repository: SourceRepositoryDep,
) -> StoryBibleCuratorProposalV1:
    """Create and persist a candidate plan without writing canonical facts."""

    bounded_context, chunk_texts = _build_project_context(
        context, project_id, repository, source_repository
    )
    try:
        proposal = curator.run(bounded_context, chunk_texts)
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="StoryBible provider request failed; check network and API settings",
        ) from error
    except (ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail="StoryBible provider returned invalid structured output",
        ) from error
    if proposal.project_id != project_id or proposal.commit_plan.project_id != project_id:
        raise HTTPException(status_code=409, detail="Curator proposal project mismatch")
    try:
        StoryBibleValidator(source_repository).validate_proposal(proposal)
        stored_plan = repository.save_candidate_plan(
            with_computed_content_hash(proposal.commit_plan)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return proposal.model_copy(update={"commit_plan": stored_plan})


@router.post(
    "/projects/{project_id}/storybible/commit-plans/{plan_id}",
    response_model=CommitPlanV1,
)
def commit_storybible_plan(
    project_id: str,
    plan_id: str,
    approval_status: ApprovalStatusBody,
    repository: StoryBibleRepositoryDep,
    source_repository: SourceRepositoryDep,
) -> CommitPlanV1:
    """Commit one project-owned candidate only after explicit approval."""

    plan = repository.get_plan(project_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="StoryBible commit plan not found")
    if approval_status != RecordStatus.APPROVED:
        raise HTTPException(status_code=403, detail="StoryBible commit plan is not approved")
    try:
        return CommitService(source_repository).commit_storybible_plan(plan, repository)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/projects/{project_id}/storybible/profiles",
    response_model=list[StoryEntityProfileV1],
)
def list_profiles(
    project_id: str,
    repository: StoryBibleRepositoryDep,
) -> list[StoryEntityProfileV1]:
    """List canonical profiles owned by the path project."""

    return repository.list_profiles(project_id)


@router.get(
    "/projects/{project_id}/storybible/profiles/{profile_id}",
    response_model=StoryEntityProfileV1,
)
def get_profile(
    project_id: str,
    profile_id: str,
    repository: StoryBibleRepositoryDep,
) -> StoryEntityProfileV1:
    """Return a canonical profile only through its owning project."""

    profile = repository.get_profile(project_id, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="StoryBible profile not found")
    return profile


@router.get(
    "/projects/{project_id}/storybible/profiles/{profile_id}/states",
    response_model=list[StoryEntityStateV1],
)
def list_profile_states(
    project_id: str,
    profile_id: str,
    repository: StoryBibleRepositoryDep,
    event_id: EventIdQuery = None,
) -> list[StoryEntityStateV1]:
    """List project-owned profile states, optionally bounded to an event anchor."""

    if repository.get_profile(project_id, profile_id) is None:
        raise HTTPException(status_code=404, detail="StoryBible profile not found")
    states = [
        resource
        for resource in repository.list_related_resources(project_id, profile_id)
        if isinstance(resource, StoryEntityStateV1)
    ]
    if event_id is None:
        return states
    return [
        state
        for state in states
        if event_id
        in {
            state.triggering_event_id,
            state.valid_from_event_id,
            state.valid_until_event_id,
        }
    ]


@router.get(
    "/projects/{project_id}/storybible/state-at",
    response_model=StoryBibleSnapshotV1,
)
def get_state_snapshot(
    project_id: str,
    event_order: EventOrderQuery,
    repository: StoryBibleRepositoryDep,
) -> StoryBibleSnapshotV1:
    """Return the resolved world state at one timeline event order.

    States established in earlier chapters remain in effect here even when the
    current chapter never mentions them, so a downstream storyboard agent always
    receives the full inherited state of characters, locations, organizations,
    active relationships, and world rules for the requested story moment.
    """

    return build_state_snapshot(repository, project_id, event_order)
