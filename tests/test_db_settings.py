from pathlib import Path

from sqlalchemy import text

from app.db import SQLITE_BUSY_TIMEOUT_MS, create_db_engine


def _file_database_url(tmp_path: Path) -> str:
    # as_posix keeps Windows paths usable inside a SQLAlchemy URL.
    return f"sqlite:///{(tmp_path / 'settings.db').as_posix()}"


def test_file_database_switches_to_wal_and_sets_busy_timeout(tmp_path: Path) -> None:
    # A value of 0 would disable waiting entirely while still matching the
    # read-back below, so pin the constant itself as well.
    assert SQLITE_BUSY_TIMEOUT_MS > 0
    engine = create_db_engine(_file_database_url(tmp_path))
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
            assert connection.scalar(text("PRAGMA busy_timeout")) == SQLITE_BUSY_TIMEOUT_MS
    finally:
        engine.dispose()


def test_memory_database_keeps_memory_journal_mode_and_still_sets_busy_timeout() -> None:
    engine = create_db_engine("sqlite://")
    try:
        with engine.connect() as connection:
            # In-memory databases cannot use WAL; asking would answer "memory".
            assert connection.scalar(text("PRAGMA journal_mode")) == "memory"
            assert connection.scalar(text("PRAGMA busy_timeout")) == SQLITE_BUSY_TIMEOUT_MS
    finally:
        engine.dispose()


def test_connection_listener_applies_to_every_new_connection(tmp_path: Path) -> None:
    engine = create_db_engine(_file_database_url(tmp_path))
    try:
        # Hold both connections at once so the pool must hand out distinct ones.
        with engine.connect() as first, engine.connect() as second:
            assert (
                first.connection.dbapi_connection
                is not second.connection.dbapi_connection
            )
            assert first.scalar(text("PRAGMA busy_timeout")) == SQLITE_BUSY_TIMEOUT_MS
            assert second.scalar(text("PRAGMA busy_timeout")) == SQLITE_BUSY_TIMEOUT_MS
    finally:
        engine.dispose()
