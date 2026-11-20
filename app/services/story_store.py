"""Persist and restore the complete story aggregate.

The mapping between the generation schema and the ORM tree lives only here so
the HTTP layer never needs to know how blueprint keys are represented in JSON
columns, or how list ordering is preserved in SQL rows.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Character,
    Choice,
    Ending,
    Episode,
    EpisodeStatus,
    Metric,
    StateChangeEntityType,
    StateChangeEventType,
    StateChangeSource,
    Story,
    StoryStateChange,
    StoryStatus,
)
from app.schemas.story_blueprint import (
    CharacterBlueprint,
    ChoiceBlueprint,
    EndingBlueprint,
    EndingCondition,
    EpisodeBlueprint,
    MetricBlueprint,
    MetricEffect,
    StoryBlueprint,
)
from app.services.blueprint_validator import BlueprintValidator


class BlueprintStorageError(ValueError):
    """Raised before writing an aggregate that fails the M1 business rules."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("blueprint cannot be stored")
        self.issues = issues


# Which generation contract this module's mapping code produces and expects.
# It lives next to the mapping (not in the schema module) because it describes
# the JSON shapes written to SQL rows, not the Pydantic types themselves.
BLUEPRINT_VERSION = 1


class BlueprintVersionError(ValueError):
    """Raised when a stored archive was produced by a different contract."""

    def __init__(self, stored: int, supported: int) -> None:
        super().__init__(
            f"stored blueprint version {stored} is not supported "
            f"(this server supports version {supported})"
        )
        self.stored = stored
        self.supported = supported


class BlueprintCorruptedError(ValueError):
    """Raised when stored JSON columns cannot be rebuilt into a blueprint.

    The API only writes archives through the validator, so this can only mean
    the database was changed outside the API: a server-side fault, not a
    client mistake.
    """

    def __init__(self) -> None:
        super().__init__("stored blueprint cannot be rebuilt")


def _require_string_list(value: object) -> list[str]:
    """Return a copy of a JSON column that must hold an array of strings.

    ``list(value)`` is not a shape check: ``list("abc")`` silently becomes
    ``["a", "b", "c"]`` and pydantic then accepts the mangled result, so a
    column hand-edited into a plain string would leave the detail endpoint
    answering 200 with rewritten data. Only an explicit ``isinstance`` check
    turns that into the corruption the 50003 contract promises.
    """
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise BlueprintCorruptedError()
    return list(value)


def _story_from_blueprint(blueprint: StoryBlueprint) -> Story:
    story = Story(
        public_id=str(uuid4()),
        title=blueprint.title,
        logline=blueprint.logline,
        genre=blueprint.genre,
        theme=blueprint.theme,
        episode_count=blueprint.episode_count,
        status=StoryStatus.READY.value,
        # Explicit, not the column default: the version must track the mapping
        # code in this module even if the schema's default ever changes.
        blueprint_version=BLUEPRINT_VERSION,
    )

    story.characters = [
        Character(
            key=character.id,
            position=position,
            name=character.name,
            role=character.role,
            goal=character.goal,
            secret=character.secret,
            personality=list(character.personality),
        )
        for position, character in enumerate(blueprint.characters)
    ]
    story.metrics = [
        Metric(
            key=metric.id,
            position=position,
            name=metric.name,
            description=metric.description,
            initial_value=metric.initial_value,
            current_value=metric.initial_value,
            low_label=metric.low_label,
            high_label=metric.high_label,
        )
        for position, metric in enumerate(blueprint.metrics)
    ]
    story.episodes = [
        Episode(
            number=episode.number,
            objective=episode.objective,
            conflict=episode.conflict,
            character_keys=list(episode.character_ids),
            required_events=list(episode.required_events),
            cliffhanger=episode.cliffhanger,
            resolution=episode.resolution,
            status=EpisodeStatus.PLANNED.value,
            choices=[
                Choice(
                    key=choice.id,
                    position=position,
                    text=choice.text,
                    intent=choice.intent,
                    consequence_hint=choice.consequence_hint,
                    effects=[
                        {"metric_key": effect.metric_id, "delta": effect.delta}
                        for effect in choice.effects
                    ],
                )
                for position, choice in enumerate(episode.choices)
            ],
        )
        for episode in blueprint.episodes
    ]
    story.endings = [
        Ending(
            key=ending.id,
            position=position,
            priority=ending.priority,
            title=ending.title,
            summary=ending.summary,
            category=ending.category,
            conditions=[
                {
                    "metric_key": condition.metric_id,
                    "operator": condition.operator,
                    "value": condition.value,
                }
                for condition in ending.conditions
            ],
        )
        for position, ending in enumerate(blueprint.endings)
    ]
    return story


def save_blueprint(session: Session, blueprint: StoryBlueprint) -> Story:
    """Save one complete story in one transaction.

    A fresh session owns and commits the transaction. If a caller already
    started a transaction, a savepoint protects the same all-or-nothing
    boundary while leaving the caller in control of the outer commit.
    """
    issues = [
        issue.as_prompt_line() for issue in BlueprintValidator().validate(blueprint)
    ]
    if issues:
        raise BlueprintStorageError(issues)

    transaction = (
        session.begin() if not session.in_transaction() else session.begin_nested()
    )
    with transaction:
        story = _story_from_blueprint(blueprint)
        session.add(story)
        # Flushing first assigns internal ids and makes a failure after this
        # point a genuine mid-transaction rollback exercise.
        session.flush()
        session.add(
            StoryStateChange(
                story=story,
                sequence=1,
                entity_type=StateChangeEntityType.STORY.value,
                entity_key=story.public_id,
                event_type=StateChangeEventType.STORY_CREATED.value,
                before_state=None,
                after_state={"status": StoryStatus.READY.value},
                source=StateChangeSource.GENERATED.value,
            )
        )
        session.flush()
    return story


def load_blueprint(session: Session, public_id: str) -> StoryBlueprint | None:
    """Load a story tree by public id and convert it back to generation shape."""
    statement = (
        select(Story)
        .where(Story.public_id == public_id)
        .options(
            selectinload(Story.characters),
            selectinload(Story.metrics),
            selectinload(Story.episodes).selectinload(Episode.choices),
            selectinload(Story.endings),
        )
    )
    # The query is inside the guard because SQLite does not enforce JSON
    # validity: a column hand-edited into text like ``abc`` is deserialized by
    # SQLAlchemy while ``session.scalar`` materialises the rows, before the
    # rebuild code below ever runs. ``json.JSONDecodeError`` is a
    # ``ValueError``, so widening the handler to ``ValueError`` is what turns
    # that shape into the same named corruption fault as the others.
    try:
        story = session.scalar(statement)
        if story is None:
            return None

        if story.blueprint_version != BLUEPRINT_VERSION:
            raise BlueprintVersionError(
                stored=story.blueprint_version,
                supported=BLUEPRINT_VERSION,
            )

        return StoryBlueprint(
            title=story.title,
            logline=story.logline,
            genre=story.genre,
            theme=story.theme,
            episode_count=story.episode_count,
            characters=[
                CharacterBlueprint(
                    id=character.key,
                    name=character.name,
                    role=character.role,
                    goal=character.goal,
                    secret=character.secret,
                    personality=_require_string_list(character.personality),
                )
                for character in story.characters
            ],
            metrics=[
                MetricBlueprint(
                    id=metric.key,
                    name=metric.name,
                    description=metric.description,
                    initial_value=metric.initial_value,
                    low_label=metric.low_label,
                    high_label=metric.high_label,
                )
                for metric in story.metrics
            ],
            episodes=[
                EpisodeBlueprint(
                    number=episode.number,
                    objective=episode.objective,
                    conflict=episode.conflict,
                    character_ids=_require_string_list(episode.character_keys),
                    required_events=_require_string_list(episode.required_events),
                    cliffhanger=episode.cliffhanger,
                    resolution=episode.resolution,
                    choices=[
                        ChoiceBlueprint(
                            id=choice.key,
                            text=choice.text,
                            intent=choice.intent,
                            effects=[
                                MetricEffect(
                                    metric_id=effect["metric_key"],
                                    delta=effect["delta"],
                                )
                                for effect in choice.effects
                            ],
                            consequence_hint=choice.consequence_hint,
                        )
                        for choice in episode.choices
                    ],
                )
                for episode in story.episodes
            ],
            endings=[
                EndingBlueprint(
                    id=ending.key,
                    title=ending.title,
                    summary=ending.summary,
                    category=ending.category,
                    conditions=[
                        EndingCondition(
                            metric_id=condition["metric_key"],
                            operator=condition["operator"],
                            value=condition["value"],
                        )
                        for condition in ending.conditions
                    ],
                    priority=ending.priority,
                )
                for ending in story.endings
            ],
        )
    # ``BlueprintVersionError`` and ``BlueprintCorruptedError`` are themselves
    # ``ValueError`` subclasses, so they are re-raised before the broad handler
    # below. Order matters: without this clause a version mismatch would become
    # a corruption 500, and the explicit shape check in ``_require_string_list``
    # would be swallowed and re-wrapped as an equivalent error with a lost
    # cause chain.
    except (BlueprintVersionError, BlueprintCorruptedError):
        raise
    # Everything caught here means the same thing: the stored archive cannot be
    # rebuilt. Two families are covered. (1) Validation and deserialisation:
    # pydantic's ``ValidationError`` subclasses ``ValueError``, and a JSON
    # column whose text is not valid JSON raises ``json.JSONDecodeError`` from
    # the row loader, also a ``ValueError``; the broad name covers both without
    # naming them individually. (2) Shapes pydantic accepts but unpacking does
    # not: a missing mapping key raises ``KeyError``, indexing a string as a
    # mapping raises ``TypeError``, and a scalar where a sequence is expected
    # raises ``TypeError``/``IndexError``/``AttributeError``. All of them become
    # the one server-fault error the API contract names.
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise BlueprintCorruptedError() from exc


def load_story_state(
    session: Session,
    public_id: str,
    *,
    change_limit: int,
) -> tuple[Story, list[StoryStateChange]] | None:
    """Load mutable play progress separately from the immutable blueprint."""
    statement = (
        select(Story)
        .where(Story.public_id == public_id)
        .options(
            selectinload(Story.metrics),
            selectinload(Story.episodes),
        )
    )
    story = session.scalar(statement)
    if story is None:
        return None

    recent_changes = list(
        session.scalars(
            select(StoryStateChange)
            .where(StoryStateChange.story_id == story.id)
            .order_by(StoryStateChange.sequence.desc())
            .limit(change_limit)
        )
    )
    return story, recent_changes


def list_stories(session: Session, *, offset: int, limit: int) -> tuple[list[Story], int]:
    """Return one summary page without loading any child entities."""
    total = session.scalar(select(func.count()).select_from(Story)) or 0
    statement = (
        select(Story)
        .order_by(Story.created_at.desc(), Story.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement)), total
