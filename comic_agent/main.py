"""FastAPI application entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import SecretStr

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.api.agent_runs import router as agent_runs_router
from comic_agent.api.documents import router as documents_router
from comic_agent.api.health import router as health_router
from comic_agent.api.pipeline import router as pipeline_router
from comic_agent.api.projects import router as projects_router
from comic_agent.api.settings import router as settings_router
from comic_agent.api.storybible import router as storybible_router
from comic_agent.api.timeline import router as timeline_router
from comic_agent.config import get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.providers.mocks import LocalSafeDemoProvider
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
            api_key=settings.llm_api_key or SecretStr(""),
            model=settings.storybible_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    )
    timeline_model = settings.timeline_model or settings.storybible_model
    app.state.timeline_agent = TimelineAgent(
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or SecretStr(""),
            model=timeline_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        provider_model=timeline_model,
    )
    if settings.fake_pipeline_demo:
        app.state.narrative_analyst_provider = LocalSafeDemoProvider(
            scenario=settings.fake_pipeline_scenario
        )
        app.state.timeline_agent = TimelineAgent(
            LocalSafeDemoProvider(scenario=settings.fake_pipeline_scenario),
            provider_model="local-safe-demo",
        )
        app.state.storybible_curator = StoryBibleCurator(
            LocalSafeDemoProvider(scenario=settings.fake_pipeline_scenario)
        )
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(agent_runs_router)
    app.include_router(documents_router)
    app.include_router(storybible_router)
    app.include_router(settings_router)
    app.include_router(timeline_router)
    app.include_router(pipeline_router)

    console_path = Path(__file__).resolve().parents[1] / "web_console" / "index.html"

    @app.get("/console/", include_in_schema=False)
    @app.get("/console/index.html", include_in_schema=False)
    def local_console() -> FileResponse:
        """Serve the existing Console from the API origin for local development."""

        return FileResponse(console_path, media_type="text/html; charset=utf-8")

    @app.get("/console/official_safe_pipeline_demo.txt", include_in_schema=False)
    def official_safe_pipeline_demo() -> FileResponse:
        """Serve the fixed local-only Console fixture without exposing source run content."""

        return FileResponse(
            console_path.with_name("official_safe_pipeline_demo.txt"),
            media_type="text/plain; charset=utf-8",
        )

    return app


app = create_app()
