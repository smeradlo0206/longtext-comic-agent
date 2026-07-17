"""FastAPI application entrypoint."""

from fastapi import FastAPI

from comic_agent.api.documents import router as documents_router
from comic_agent.api.health import router as health_router
from comic_agent.api.projects import router as projects_router
from comic_agent.config import get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory


def create_app(database_url: str | None = None) -> FastAPI:
    """Create the FastAPI app with an isolated database binding."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    engine = make_engine(database_url or settings.database_url)
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(documents_router)
    return app


app = create_app()
