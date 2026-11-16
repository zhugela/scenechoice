"""M2 batch 1: six domain entities plus the state-change log.

Revision ID: 20261115_0001
Revises:
Create Date: 2026-11-15

Creates exactly seven tables:
    stories, characters, metrics, episodes, choices, endings,
    story_state_changes

The DDL mirrors app/models/ one-for-one. Business rules that span fields
(character/metric/ending counts, effect targets, ...) are NOT duplicated here;
they remain in app/services/blueprint_validator.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261115_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("logline", sa.String(length=200), nullable=False),
        sa.Column("genre", sa.String(length=40), nullable=False),
        sa.Column("theme", sa.String(length=100), nullable=False),
        sa.Column("episode_count", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("blueprint_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "episode_count IN (3, 5)", name="ck_stories_episode_count"
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'in_progress', 'completed', 'abandoned')",
            name="ck_stories_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stories"),
    )
    op.create_index("ix_stories_public_id", "stories", ["public_id"], unique=True)

    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=False),
        sa.Column("secret", sa.String(length=200), nullable=False),
        sa.Column("personality", sa.JSON(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_characters_position"),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_characters_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_characters"),
        sa.UniqueConstraint("story_id", "key", name="uq_characters_story_key"),
    )
    op.create_index("ix_characters_story_id", "characters", ["story_id"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("description", sa.String(length=150), nullable=False),
        sa.Column("initial_value", sa.SmallInteger(), nullable=False),
        sa.Column("low_label", sa.String(length=30), nullable=False),
        sa.Column("high_label", sa.String(length=30), nullable=False),
        sa.Column("current_value", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "initial_value BETWEEN 0 AND 100", name="ck_metrics_initial_value"
        ),
        sa.CheckConstraint(
            "current_value BETWEEN 0 AND 100", name="ck_metrics_current_value"
        ),
        sa.CheckConstraint("position >= 0", name="ck_metrics_position"),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_metrics_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metrics"),
        sa.UniqueConstraint("story_id", "key", name="uq_metrics_story_key"),
    )
    op.create_index("ix_metrics_story_id", "metrics", ["story_id"])

    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.SmallInteger(), nullable=False),
        sa.Column("objective", sa.String(length=200), nullable=False),
        sa.Column("conflict", sa.String(length=200), nullable=False),
        sa.Column("character_keys", sa.JSON(), nullable=False),
        sa.Column("required_events", sa.JSON(), nullable=False),
        sa.Column("cliffhanger", sa.String(length=200), nullable=True),
        sa.Column("resolution", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint("number BETWEEN 1 AND 5", name="ck_episodes_number_range"),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed')",
            name="ck_episodes_status",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_episodes_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_episodes"),
        sa.UniqueConstraint("story_id", "number", name="uq_episodes_story_number"),
    )
    op.create_index("ix_episodes_story_id", "episodes", ["story_id"])

    op.create_table(
        "choices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("episode_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.String(length=120), nullable=False),
        sa.Column("intent", sa.String(length=120), nullable=False),
        sa.Column("consequence_hint", sa.String(length=200), nullable=False),
        sa.Column("effects", sa.JSON(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_choices_position"),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episodes.id"],
            name="fk_choices_episode_id_episodes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_choices"),
        sa.UniqueConstraint("episode_id", "key", name="uq_choices_episode_key"),
    )
    op.create_index("ix_choices_episode_id", "choices", ["episode_id"])

    op.create_table(
        "endings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "category IN ('low', 'high', 'mixed')", name="ck_endings_category"
        ),
        sa.CheckConstraint("priority >= 1", name="ck_endings_priority"),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_endings_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_endings"),
        sa.UniqueConstraint("story_id", "key", name="uq_endings_story_key"),
    )
    op.create_index("ix_endings_story_id", "endings", ["story_id"])

    op.create_table(
        "story_state_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_key", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_story_state_changes_sequence"),
        sa.CheckConstraint(
            "source IN ('generated', 'player', 'system')",
            name="ck_story_state_changes_source",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_story_state_changes_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_state_changes"),
        sa.UniqueConstraint(
            "story_id", "sequence", name="uq_story_state_changes_story_sequence"
        ),
    )
    op.create_index(
        "ix_story_state_changes_story_id", "story_state_changes", ["story_id"]
    )
    op.create_index(
        "ix_story_state_changes_story_entity",
        "story_state_changes",
        ["story_id", "entity_type", "entity_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_story_state_changes_story_entity", table_name="story_state_changes"
    )
    op.drop_index(
        "ix_story_state_changes_story_id", table_name="story_state_changes"
    )
    op.drop_table("story_state_changes")

    op.drop_index("ix_endings_story_id", table_name="endings")
    op.drop_table("endings")

    op.drop_index("ix_choices_episode_id", table_name="choices")
    op.drop_table("choices")

    op.drop_index("ix_episodes_story_id", table_name="episodes")
    op.drop_table("episodes")

    op.drop_index("ix_metrics_story_id", table_name="metrics")
    op.drop_table("metrics")

    op.drop_index("ix_characters_story_id", table_name="characters")
    op.drop_table("characters")

    op.drop_index("ix_stories_public_id", table_name="stories")
    op.drop_table("stories")
