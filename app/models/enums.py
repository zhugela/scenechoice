"""Controlled vocabulary for persisted state.

The values are stored as plain ``String`` columns with CHECK constraints rather
than SQL enum types: SQLite has no native enum, and string columns keep
Alembic diffs, manual inspection, and future value additions simple. These
members are the single vocabulary the future service/repository layer should
import instead of re-typing literals.
"""

from __future__ import annotations

from enum import StrEnum


class StoryStatus(StrEnum):
    READY = "ready"  # Blueprint persisted; the player has not started yet.
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"  # An ending was reached.
    ABANDONED = "abandoned"


class EpisodeStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class EndingCategory(StrEnum):
    LOW = "low"
    HIGH = "high"
    MIXED = "mixed"


class StateChangeSource(StrEnum):
    GENERATED = "generated"  # Written by the generation/import flow.
    PLAYER = "player"  # Caused by a player action.
    SYSTEM = "system"  # Migration, repair, or administrative action.


class StateChangeEntityType(StrEnum):
    STORY = "story"
    EPISODE = "episode"
    CHOICE = "choice"
    METRIC = "metric"
    ENDING = "ending"


class StateChangeEventType(StrEnum):
    STORY_CREATED = "story_created"
    STORY_STATUS_CHANGED = "story_status_changed"
    EPISODE_STATUS_CHANGED = "episode_status_changed"
    CHOICE_SELECTED = "choice_selected"
    METRIC_CHANGED = "metric_changed"
    ENDING_REACHED = "ending_reached"
