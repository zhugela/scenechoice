"""Database engine and request-scoped session provider."""

import logging
import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

# How long a SQLite connection waits for a competing lock before failing with
# "database is locked". This is the wait-for-lock deadline only; it is a
# different knob from SQLAlchemy's ``connect_args={"timeout": ...}``/pysqlite
# timeout, which bounds the initial connection attempt. 5s is longer than a
# single request's write transaction but short enough that a wedged request
# fails instead of hanging the caller indefinitely.
SQLITE_BUSY_TIMEOUT_MS = 5000


def _is_memory_database(database_url: str) -> bool:
    """Return True for SQLite in-memory databases, which cannot use WAL."""
    database = make_url(database_url).database
    return not database or ":memory:" in database


def _enable_sqlite_wal(db_engine: Engine) -> None:
    """Switch a file-backed SQLite database to WAL mode once at startup.

    WAL is a persistent property of the database file, so setting it once is
    enough; setting it again on an already-WAL database is a no-op. In-memory
    databases answer ``memory`` here and gain nothing, so the caller skips them.
    A failure (for example another connection holding a lock) must not stop the
    application from starting, so it is logged and ignored.
    """
    try:
        with db_engine.connect() as connection:
            journal_mode = connection.execute(text("PRAGMA journal_mode=WAL")).scalar()
    except (SQLAlchemyError, sqlite3.Error, OSError):
        logger.warning(
            "Could not switch SQLite to WAL mode; continuing with the current "
            "journal mode. Possible causes: another connection holds a lock on "
            "the database, the file is read-only, or the filesystem does not "
            "support WAL.",
            exc_info=True,
        )
        return

    if str(journal_mode).lower() != "wal":
        logger.warning(
            "SQLite journal_mode is %r instead of 'wal'; continuing with the "
            "current journal mode. Possible causes: another connection holds a "
            "lock on the database during the switch, or the filesystem does not "
            "support WAL.",
            journal_mode,
        )


def create_db_engine(database_url: str):
    """Build an engine and apply SQLite connection- and database-level settings."""
    db_engine = create_engine(database_url)
    if db_engine.dialect.name != "sqlite":
        return db_engine

    @event.listens_for(db_engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
        """SQLite settings that must be applied to every new connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()

    if not _is_memory_database(database_url):
        _enable_sqlite_wal(db_engine)

    return db_engine


engine = create_db_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Yield one session and always return its connection to the pool."""
    with SessionLocal() as session:
        yield session
