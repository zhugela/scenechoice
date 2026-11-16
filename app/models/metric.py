"""A story-scoped metric definition plus its current (mutable) value."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.story import Story


class Metric(Base):
    """One of the story's two dynamic state dimensions.

    World-fact split:
    * ``name``/``description``/``initial_value``/``low_label``/``high_label``
      are narrative framing and are immutable after import.
    * ``current_value`` is the live world fact. It is the only column in this
      table that changes during play, and every change must be paired with a
      ``StoryStateChange`` row in the same transaction (batch 3).

    ``current_value`` intentionally has no default. The importer must copy
    ``initial_value`` explicitly, so a new archive can never start at an
    accidental 0 just because a default kicked in.
    """

    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint("story_id", "key", name="uq_metrics_story_key"),
        CheckConstraint(
            "initial_value BETWEEN 0 AND 100", name="ck_metrics_initial_value"
        ),
        CheckConstraint(
            "current_value BETWEEN 0 AND 100", name="ck_metrics_current_value"
        ),
        CheckConstraint("position >= 0", name="ck_metrics_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # --- Immutable narrative / rules ---------------------------------------
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(150), nullable=False)
    initial_value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    low_label: Mapped[str] = mapped_column(String(30), nullable=False)
    high_label: Mapped[str] = mapped_column(String(30), nullable=False)

    # --- Mutable world fact (no default: importer copies initial_value) -----
    current_value: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    story: Mapped["Story"] = relationship(back_populates="metrics")
