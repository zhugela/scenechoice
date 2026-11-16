"""One episode of a story, with its planned narrative and play status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import EpisodeStatus

if TYPE_CHECKING:
    from app.models.choice import Choice
    from app.models.story import Story


class Episode(Base):
    """One planned episode.

    The natural business key is ``(story_id, number)``: the blueprint already
    identifies episodes by their 1..5 number, so no extra string key is needed.

    ``character_keys`` and ``required_events`` are JSON arrays rather than join
    tables. This batch's acceptance fixes the schema at six entity tables plus
    one state-change table, and the referenced entities are story-scoped, so
    the service layer resolves and validates these keys at import time. The
    JSON layout is documented here so batch 2/3 does not have to guess:

        character_keys  -> ["lin", "zhou"]
        required_events -> ["the letter arrives", "the bridge burns"]

    Narrative columns are written once at import. Only ``status`` changes
    during play, and every change must append a ``StoryStateChange``.
    """

    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("story_id", "number", name="uq_episodes_story_number"),
        CheckConstraint("number BETWEEN 1 AND 5", name="ck_episodes_number_range"),
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed')",
            name="ck_episodes_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # --- Immutable narrative ------------------------------------------------
    objective: Mapped[str] = mapped_column(String(200), nullable=False)
    conflict: Mapped[str] = mapped_column(String(200), nullable=False)
    character_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_events: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cliffhanger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # --- Mutable play state -------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EpisodeStatus.PLANNED.value
    )

    story: Mapped["Story"] = relationship(back_populates="episodes")
    choices: Mapped[list["Choice"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Choice.position",
    )
