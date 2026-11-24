"""M3 batch 1: cache one narration per player event.

Revision ID: 20261123_0004
Revises: 20261122_0003
Create Date: 2026-11-23

The DDL mirrors ``app/models/narration.py`` one-for-one. ``(story_id,
sequence)`` is unique so two first requests for the same event cannot both
store a narration; the service layer resolves the loser's ``IntegrityError`` by
re-reading the winner. ``ON DELETE CASCADE`` keeps the cache part of the story
aggregate: deleting a story removes its narration rows with it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261123_0004"
down_revision: str | Sequence[str] | None = "20261122_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "narrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_narrations_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_narrations"),
        sa.UniqueConstraint(
            "story_id", "sequence", name="uq_narrations_story_sequence"
        ),
    )
    op.create_index("ix_narrations_story_id", "narrations", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_narrations_story_id", table_name="narrations")
    op.drop_table("narrations")
