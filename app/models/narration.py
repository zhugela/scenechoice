"""One cached narration for one player event.

Why a table instead of regenerating on every read
-------------------------------------------------
A narration is a model call, so "same turn, same text" is a cost decision as
much as a consistency one. ``(story_id, sequence)`` is unique: the first request
for an event writes the row, every later request replays it without touching the
provider. The unique constraint is also the concurrency guard — when two first
requests race, the loser reads the winner's row instead of returning a 500.

Narrative vs world fact
-----------------------
The text is immutable once written. A regenerated variant would silently change
what the player already read, and the archive's event log is append-only, so the
narration of a past event must stay append-only too. Regenerating means
requesting a different event, not rewriting this row.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.story import Story


class Narration(Base):
    """The narrative text produced for one ``story_state_changes.sequence``."""

    __tablename__ = "narrations"
    __table_args__ = (
        UniqueConstraint(
            "story_id", "sequence", name="uq_narrations_story_sequence"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The play event this text describes (``story_state_changes.sequence``).
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)

    # What this one generation cost. Nullable because a reply may omit usage.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    story: Mapped["Story"] = relationship(back_populates="narrations")
