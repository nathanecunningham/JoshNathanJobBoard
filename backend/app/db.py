"""SQLite engine and session handling.

Two PRAGMAs are applied to every new connection:

- ``foreign_keys=ON`` — SQLite does NOT enforce foreign keys by default;
  without this, orphaned rows would insert silently.
- ``journal_mode=WAL`` — write-ahead logging, so a slow writer never blocks
  readers (keeps the tracker responsive during long operations).
"""

from collections.abc import Generator

from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

from app.config import get_settings


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_engine(database_path: str) -> Engine:
    """Create a SQLite engine with the required PRAGMAs on every connection."""
    engine = create_engine(
        f"sqlite:///{database_path}",
        # FastAPI may serve requests from different threads; SQLite's default
        # same-thread check is too strict for that, and sessions are still
        # used from one thread at a time.
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the application's engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_db_engine(get_settings().database_path)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    with Session(get_engine()) as session:
        yield session
