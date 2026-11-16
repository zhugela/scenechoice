"""Append-only record of persisted story state transitions.

This is the "state changes must be traceable" capability from M2. This batch
only creates the structure; writing rows belongs to batch 3 when transactions
and the rule engine exist.

Design choices:
* Append-only: the table has ``occurred_at`` but no ``updated_at``. Rows are
  never edited or deleted individually; they leave only when their whole story
  aggregate is deleted.
* ``sequence`` is a per-story monotonic counter (starting at 1) assigned by the
  writer inside the same transaction. ``UNIQUE (story_id, sequence)`` makes a
  duplicated transition impossible even if two writers race.
* Polymorphic target (``entity_type`` + ``entity_key``) instead of five
  nullable foreign keys: the history must be able to name a story, episode,
  choice, metric, or ending without a wide sparse table. ``entity_key`` uses
  the business key (story ``public_id``; episode ``number`` as text; choice/
  metric/ending ``key``), never the internal integer id.
* ``before_state``/``after_state`` are JSON snapshots of only the fields that
  changed, for example ``{"current_value": 40}`` -> ``{"current_value": 50}``.
  Keeping the same transaction append guarantees the snapshot matches the row
  it describes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.story import Story


class StoryStateChange(Base):
    """One immutable transition in a story archive's timeline."""

    __tablename__ = "story_state_changes"
    __table_args__ = (
        UniqueConstraint(
            "story_id", "sequence", name="uq_story_state_changes_story_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_story_state_changes_sequence"),
        CheckConstraint(
            "source IN ('generated', 'player', 'system')",
            name="ck_story_state_changes_source",
        ),
        Index(
            "ix_story_state_changes_story_entity",
            "story_id",
            "entity_type",
            "entity_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- What changed -------------------------------------------------------
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)

    # --- Snapshot -----------------------------------------------------------
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # --- Provenance ---------------------------------------------------------
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    story: Mapped["Story"] = relationship(back_populates="state_changes")
