"""A story-scoped character definition (world fact + narrative)."""

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

if TYPE_CHECKING:
    from app.models.story import Story


class Character(Base):
    """One character belonging to a story.

    ``key`` is the blueprint's ``CharacterBlueprint.id`` (for example
    ``"lin"``). It is unique only inside its story, which is why the global
    primary key stays an internal integer and the business key is protected by
    ``UNIQUE (story_id, key)``. Effects/choice/ending JSON reference these
    story-scoped keys, never the internal row ids.
    """

    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("story_id", "key", name="uq_characters_story_key"),
        CheckConstraint("position >= 0", name="ck_characters_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    # SQL rows have no intrinsic order; position preserves blueprint order so
    # prompts and the reading UI stay reproducible after a reload.
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # --- Immutable narrative ------------------------------------------------
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    goal: Mapped[str] = mapped_column(String(200), nullable=False)
    # Secrets are narrative facts the player has not learned yet. They must not
    # be copied into request logs or player-visible payloads by later layers.
    secret: Mapped[str] = mapped_column(String(200), nullable=False)
    personality: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    story: Mapped["Story"] = relationship(back_populates="characters")
