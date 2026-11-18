"""A reachable ending definition and its deterministic conditions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.story import Story


class Ending(Base):
    """One of the story's at least three reachable endings.

    ``conditions`` are world facts (they decide reachability) stored as JSON
    for the same seven-table constraint as choices. Layout:

        [{"metric_key": "trust", "operator": "gte", "value": 70}]

    ``position`` preserves the blueprint array order, while ``priority`` is the
    rule engine's evaluation order. They are separate because priorities may be
    valid in any unique order, not only ascending order. Whether an ending has
    actually been reached is *not* stored here: that is play state, recorded as
    a ``StoryStateChange`` event so the history remains the single timeline.
    """

    __tablename__ = "endings"
    __table_args__ = (
        UniqueConstraint("story_id", "key", name="uq_endings_story_key"),
        CheckConstraint(
            "category IN ('low', 'high', 'mixed')", name="ck_endings_category"
        ),
        CheckConstraint("priority >= 1", name="ck_endings_priority"),
        CheckConstraint("position >= 0", name="ck_endings_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    # SQL rows have no intrinsic order; position preserves the blueprint list.
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # --- Immutable narrative ------------------------------------------------
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(10), nullable=False)

    # --- Immutable world facts (JSON, validated at import) ------------------
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    story: Mapped["Story"] = relationship(back_populates="endings")
