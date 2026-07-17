"""FastAPI dependencies."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from comic_agent.repositories.source_repository import SourceRepository


def get_repository(request: Request) -> Iterator[SourceRepository]:
    """Yield a repository bound to the app session factory."""

    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield SourceRepository(session)
    finally:
        session.close()
