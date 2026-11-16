"""A player choice attached to one episode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    from app.models.episode import Episode


class Choice(Base):
    """One of the two fixed choices offered by an episode.

    ``text``/``intent``/``consequence_hint`` are narrative and immutable after
    import. ``effects`` are world facts (deterministic metric deltas) but are
    stored as a JSON array for this batch, because the accepted schema is six
    entity tables + one state-change table (no separate effect table). Layout:

        [{"metric_key": "trust", "delta": 10}]

    Consequence: SQLite cannot enforce a foreign key inside JSON. The importer
    (batch 3) must reject unknown metric keys before writing; a bad effect
    would otherwise be discovered only when the rule engine applies it.
    """

    __tablename__ = "choices"
    __table_args__ = (
        UniqueConstraint("episode_id", "key", name="uq_choices_episode_key"),
        CheckConstraint("position >= 0", name="ck_choices_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # --- Immutable narrative ------------------------------------------------
    text: Mapped[str] = mapped_column(String(120), nullable=False)
    intent: Mapped[str] = mapped_column(String(120), nullable=False)
    consequence_hint: Mapped[str] = mapped_column(String(200), nullable=False)

    # --- Immutable world facts (JSON, validated at import) ------------------
    effects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    episode: Mapped["Episode"] = relationship(back_populates="choices")
