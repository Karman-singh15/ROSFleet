"""
Database session management.

One engine, one session factory, one FastAPI dependency. Every request gets
its own session and it is always closed, including when the handler raises.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# check_same_thread is a SQLite-only quirk: by default a SQLite connection
# may only be used by the thread that created it, which breaks FastAPI's
# threadpool. Harmless to relax here because each request has its own session.
connect_args = ({"check_same_thread": False}
                if settings.database_url.startswith("sqlite") else {})

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Recycle connections before PostgreSQL's idle timeout kills them,
    # otherwise the first request after a quiet night fails.
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for every ORM model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create tables that do not exist yet.

    Fine for this project's scale. A production system would use Alembic
    migrations instead, which is why alembic is in requirements.txt.
    """
    from app import models  # noqa: F401  (registers the models on Base)
    Base.metadata.create_all(bind=engine)
