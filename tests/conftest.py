from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.source_repository import SourceRepository


@pytest.fixture()
def temp_repository(tmp_path: Path) -> Iterator[SourceRepository]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    try:
        yield SourceRepository(session)
    finally:
        session.close()
        engine.dispose()
