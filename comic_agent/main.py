"""FastAPI application entrypoint."""

from fastapi import FastAPI

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.api.documents import router as documents_router
from comic_agent.api.health import router as health_router
from comic_agent.api.projects import router as projects_router
from comic_agent.api.storybible import router as storybible_router
from comic_agent.api.timeline import router as timeline_router
from comic_agent.config import get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.providers.openai_compatible import OpenAICompatibleProvider


def create_app(database_url: str | None = None) -> FastAPI:
    """Create the FastAPI app with an isolated database binding."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    engine = make_engine(database_url or settings.database_url)
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.storybible_curator = StoryBibleCurator(
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.storybible_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
    timeline_model = settings.timeline_model or settings.storybible_model
    app.state.timeline_agent = TimelineAgent(
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=timeline_model,
            timeout_seconds=settings.timeline_llm_timeout_seconds,
            max_retries=settings.timeline_llm_max_retries,
        ),
        provider_model=timeline_model,
        llm_enabled=settings.timeline_llm_enabled,
    )
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(documents_router)
    app.include_router(storybible_router)
    app.include_router(timeline_router)
    return app


app = create_app()
