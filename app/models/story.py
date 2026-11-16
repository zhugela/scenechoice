"""Root aggregate: one persisted, replayable story archive."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import StoryStatus

if TYPE_CHECKING:
    from app.models.character import Character
    from app.models.ending import Ending
    from app.models.episode import Episode
    from app.models.metric import Metric
    from app.models.state_change import StoryStateChange


class Story(Base):
    """A story archive.

    Identity strategy (deliberate, see docs in ``app/models/__init__.py``):
    ``id`` is an internal INTEGER PRIMARY KEY for compact SQLite rowids and
    fast joins, while ``public_id`` is the UUID that may leave the process
    (API, URLs, logs). Exposing only the UUID prevents callers from guessing
    other players' stories, and it stays stable even if the archive is ever
    re-imported into another database.

    Mutation boundary:
    * Narrative columns (title/logline/genre/theme) are written once at import.
      Editing a generated story means creating a new archive, not patching text
      in place, so the narrative stays consistent with its validated blueprint.
    * ``status`` and ``blueprint_version`` are persistence-only state. Every
      future status change must append a ``StoryStateChange`` row in the same
      transaction; the table structure exists, the writer is batch 2/3 work.
    """

    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint("episode_count IN (3, 5)", name="ck_stories_episode_count"),
        CheckConstraint(
            "status IN ('ready', 'in_progress', 'completed', 'abandoned')",
            name="ck_stories_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid4()),
    )

    # --- Immutable narrative (copied from the validated blueprint) ----------
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    logline: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[str] = mapped_column(String(40), nullable=False)
    theme: Mapped[str] = mapped_column(String(100), nullable=False)
    episode_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # --- Mutable play state -------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StoryStatus.READY.value
    )
    # Which generation contract produced the stored JSON shapes. Bump it when
    # the blueprint/JSON layout changes so old archives stay interpretable.
    blueprint_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    # Children form one aggregate: a story is meaningless without them, so a
    # Story delete removes the whole archive. The FK also declares ON DELETE
    # CASCADE, and passive_deletes lets SQLite do the work without loading
    # every child row (requires PRAGMA foreign_keys=ON on each connection).
    characters: Mapped[list["Character"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Character.position",
    )
    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Metric.position",
    )
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Episode.number",
    )
    endings: Mapped[list["Ending"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Ending.priority",
    )
    state_changes: Mapped[list["StoryStateChange"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryStateChange.sequence",
    )
