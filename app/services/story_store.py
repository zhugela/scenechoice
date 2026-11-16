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


def _story_from_blueprint(blueprint: StoryBlueprint) -> Story:
    story = Story(
        public_id=str(uuid4()),
        title=blueprint.title,
        logline=blueprint.logline,
        genre=blueprint.genre,
        theme=blueprint.theme,
        episode_count=blueprint.episode_count,
        status=StoryStatus.READY.value,
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
        for ending in blueprint.endings
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
    story = session.scalar(statement)
    if story is None:
        return None

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
                personality=list(character.personality),
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
                character_ids=list(episode.character_keys),
                required_events=list(episode.required_events),
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
