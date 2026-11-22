"""Declarative base shared by every persisted SceneChoice entity.

Layer boundary
--------------
This package is the **persistence** layer: it answers "what must survive a
restart?" and deliberately knows nothing about HTTP, prompts, retries, or the
M1 generation rules. Shape validation for generated content stays in
``app/schemas/story_blueprint.py``; cross-field business rules stay in
``app/services/blueprint_validator.py``. The generation-state ->
persistence-state mapping is documented in ``app/models/__init__.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


# Deterministic constraint names keep Alembic diffs stable across SQLite's
# batch-mode table rewrites, where unnamed constraints cannot be referenced.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Return an aware UTC timestamp.

    SQLite has no native timezone type: the value is stored as wall-clock text
    and read back naive. Every writer must therefore use UTC so archives stay
    comparable across machines and timezones.
    """
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Restore the UTC timezone label on a timestamp read from persistence.

    This is the read-side counterpart of :func:`utcnow`: write timestamps in
    UTC, then restore the UTC label on read. Naive values are treated as UTC
    wall-clock time, while aware values are converted to UTC without changing
    the instant. ``None`` stays ``None``.
    """
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Single metadata object used by Alembic autogenerate and migrations."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
