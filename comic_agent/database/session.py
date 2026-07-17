"""Database engine and session helpers."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the configured database."""

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the application session factory."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
