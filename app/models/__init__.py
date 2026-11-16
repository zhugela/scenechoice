"""SceneChoice persistence models (M2, batch 1).

This package is the storage contract. It is intentionally not the same thing as
the generation contract in ``app/schemas/story_blueprint.py``.

Why two models instead of reusing the Pydantic schema
-----------------------------------------------------
``StoryBlueprint`` exists to judge one model response: it forbids extra fields,
counts list items, and checks ranges. It has no identity, no timestamps, no
current metric values, and no place to record what happened during play.
Turning it into an ORM model would blur "what the model must return" with "what
must survive a restart", and would make the validator's rules depend on the
database schema.

The ORM models therefore add only persistence concerns and deliberately do not
re-implement the ten business rules. Local invariants are enforced in SQLite
(foreign keys, uniqueness, 0..100 metrics, 1..5 episode numbers). Cross-field
rules (2-4 characters, exactly 2 metrics, exactly 2 choices per episode, >=3
endings, ending conditions mentioning known metrics, ...) stay in
``BlueprintValidator`` as the single source of truth. Duplicating them in DDL
would let the two copies drift, which is exactly the class of bug M1 spent
several rounds fixing.

Generation -> persistence mapping
---------------------------------
=====================  =====================================================
StoryBlueprint         Persistence
=====================  =====================================================
(no story identity)    ``Story.public_id`` UUID + internal integer ``id``
title/logline/genre/   ``Story`` columns (immutable after import)
theme
episode_count          ``Story.episode_count`` + CHECK (3, 5)
characters[].id        ``Character.key``; ``UNIQUE (story_id, key)``
characters order       ``Character.position`` (SQL rows have no order)
characters[].*         ``Character`` narrative columns
metrics[].id           ``Metric.key``; ``UNIQUE (story_id, key)``
metrics[].initial_     ``Metric.initial_value``; ``current_value`` starts as a
value                  copy at import and is the only mutable metric column
episodes[].number      ``Episode.number``; ``UNIQUE (story_id, number)``
episodes[].character_  ``Episode.character_keys`` JSON array (story-scoped keys)
ids
episodes[].required_   ``Episode.required_events`` JSON array
events
episodes[].choices     ``Choice`` rows; order preserved by ``position``
choices[].effects      ``Choice.effects`` JSON array of
                       ``{"metric_key", "delta"}``
endings[].conditions   ``Ending.conditions`` JSON array of
                       ``{"metric_key", "operator", "value"}``
=====================  =====================================================

Persistence-only fields: surrogate keys, ``public_id``, ``status``,
``blueprint_version``, ``created_at``/``updated_at``, and the entire
``story_state_changes`` table.

Fact vs narrative
-----------------
* Narrative (written once, immutable after import): story title/logline/genre/
  theme; character name/role/goal/secret/personality; episode objective/
  conflict/required events/cliffhanger/resolution; choice text/intent/
  consequence hint; ending title/summary.
* World facts (decide outcomes): metric definitions and ``current_value``,
  choice ``effects``, ending ``conditions``, episode/choice ordering.
* Facts that change during play are limited to ``Story.status``,
  ``Episode.status`` and ``Metric.current_value``. Every change must append a
  ``StoryStateChange`` in the same transaction (writer is batch 3).
* "Immutable after import" is a service-layer rule, not a database trigger:
  this batch creates structure only, and SQLite triggers would make batch-3
  transactions and future re-imports harder to reason about.

ID strategy
-----------
Hybrid keys, chosen for three concrete reasons:
1. SQLite ``INTEGER PRIMARY KEY`` is the rowid: compact, fast to join, and the
   natural target for foreign keys. Pure UUID primary keys would widen every
   child row's FK and slow scans for no benefit inside one file.
2. Blueprint ids (``"lin"``, ``"trust"``, ...) are model-generated and only
   unique within a story. Promoting them to global primary keys would let two
   stories collide; they become story-scoped business keys with a composite
   UNIQUE constraint.
3. The only identifier that leaves the process is ``Story.public_id`` (UUID).
   HTTP clients must not be able to enumerate integer ids, and a UUID survives
   exporting/re-importing an archive into another database.

Cascade / aggregate boundary
----------------------------
A story is the aggregate root. Characters, metrics, episodes, endings and state
changes are story-owned; choices are episode-owned. All foreign keys declare
``ON DELETE CASCADE`` and all relationships use ``cascade="all,
delete-orphan"`` with ``passive_deletes=True``: deleting a story is meant to
remove the whole archive, and the database can do it without loading every
child. There is deliberately no soft-delete flag in this batch.

Operational notes for batch 2/3
-------------------------------
* SQLite disables foreign keys per connection by default. The future engine
  factory must execute ``PRAGMA foreign_keys=ON`` on every connection, or the
  declared cascades silently do nothing.
* ``sqlite:///./scenechoice.db`` is relative to the process working directory.
  Run the app and Alembic from the repository root, or set
  ``SCENECHOICE_DATABASE_URL`` to an absolute path.
* SQLite stores datetime as wall-clock text; writers use UTC (see
  ``app.models.base.utcnow``) and readers must treat naive values as UTC.
* JSON columns are not validated by SQLite. Import (batch 3) must verify that
  every ``metric_key`` exists in the same story before writing.

Out of scope in this batch: engine/session factories, repositories, services,
API wiring, archive restore, and the state-change writer.
"""

from app.models.base import Base, utcnow
from app.models.character import Character
from app.models.choice import Choice
from app.models.ending import Ending
from app.models.enums import (
    EndingCategory,
    EpisodeStatus,
    StateChangeEntityType,
    StateChangeEventType,
    StateChangeSource,
    StoryStatus,
)
from app.models.episode import Episode
from app.models.metric import Metric
from app.models.state_change import StoryStateChange
from app.models.story import Story

__all__ = [
    "Base",
    "Character",
    "Choice",
    "Ending",
    "EndingCategory",
    "Episode",
    "EpisodeStatus",
    "Metric",
    "StateChangeEntityType",
    "StateChangeEventType",
    "StateChangeSource",
    "Story",
    "StoryStateChange",
    "StoryStatus",
    "utcnow",
]
