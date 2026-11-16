"""Database engine and request-scoped session provider."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def create_db_engine(database_url: str):
    """Build an engine and apply SQLite connection-level safety settings."""
    db_engine = create_engine(database_url)
    if db_engine.dialect.name != "sqlite":
        return db_engine

    @event.listens_for(db_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        """SQLite needs this per connection for cascade deletes to work."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return db_engine


engine = create_db_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Yield one session and always return its connection to the pool."""
    with SessionLocal() as session:
        yield session
