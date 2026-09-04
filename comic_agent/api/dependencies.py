"""FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.provider_circuit_repository import ProviderCircuitRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository


def get_session(request: Request) -> Iterator[Session]:
    """Yield a database session bound to the app session factory."""

    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_repository(session: SessionDep) -> SourceRepository:
    """Return a source repository bound to the request session."""

    return SourceRepository(session)


def get_agent_run_repository(session: SessionDep) -> AgentRunRepository:
    """Return an AgentRun repository bound to the request session."""

    return AgentRunRepository(session)


def get_comic_production_repository(session: SessionDep) -> ComicProductionRepository:
    """Return comic production persistence bound to the request session."""

    return ComicProductionRepository(session)


def get_narrative_analysis_repository(session: SessionDep) -> NarrativeAnalysisRepository:
    """Return whole-document analysis persistence bound to the request session."""

    return NarrativeAnalysisRepository(session)


def get_narrative_analysis_recovery_repository(
    session: SessionDep,
) -> NarrativeAnalysisRecoveryRepository:
    """Return append-only Stage B recovery persistence bound to the request session."""

    return NarrativeAnalysisRecoveryRepository(session)


def get_timeline_gate3_repository(session: SessionDep) -> TimelineGate3Repository:
    """Return read/write Timeline Gate 3 persistence bound to the request session."""

    return TimelineGate3Repository(session)


def get_provider_circuit_repository(session: SessionDep) -> ProviderCircuitRepository:
    """Return durable, source-free Provider circuit persistence."""

    return ProviderCircuitRepository(session)
