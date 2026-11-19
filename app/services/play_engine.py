"""Deterministic player-choice executor.

The model writes the blueprint once. From then on arithmetic, episode order and
ending selection are Python's job: the same choice must always produce the same
number, and the same metric state must always pick the same ending.

Every mutation appends a ``StoryStateChange`` row so the event log stays the
single timeline — the metric row holds the current fact, the log holds how it
got there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Choice,
    Ending,
    Episode,
    EpisodeStatus,
    StateChangeEntityType,
    StateChangeEventType,
    StateChangeSource,
    Story,
    StoryStateChange,
    StoryStatus,
)
from app.services.conditions import clamp_metric, conditions_all_match

FINISHED_STATUSES = (StoryStatus.COMPLETED.value, StoryStatus.ABANDONED.value)


class PlayError(Exception):
    """A player action the story's current state cannot honour."""

    code = "play_error"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class StoryNotFound(PlayError):
    code = "story_not_found"


class StoryFinished(PlayError):
    code = "story_finished"


class ChoiceNotInCurrentEpisode(PlayError):
    code = "choice_not_in_current_episode"


class BrokenBlueprint(PlayError):
    """Persisted data the engine cannot play; validation should have caught it."""

    code = "broken_blueprint"


class NoMatchingEnding(PlayError):
    """The blueprint passed reachability validation, so this means the data was changed by hand."""

    code = "no_matching_ending"


@dataclass(frozen=True)
class PlayOutcome:
    """What one player choice did, in the shape the HTTP layer needs to answer."""

    story_public_id: str
    story_status: str
    episode_number: int
    next_episode_number: int | None
    metrics: dict[str, int] = field(default_factory=dict)
    ending_key: str | None = None
    sequence: int = 0


def current_episode(story: Story) -> Episode:
    """The episode being played: the ``in_progress`` one, else episode 1 of a fresh story.

    Anything else (no episodes, or a story that claims to be in progress while
    every episode is completed or still planned) is broken data, not player
    input — say so instead of silently restarting at episode 1.
    """
    ordered = sorted(story.episodes, key=lambda item: item.number)
    if not ordered:
        raise BrokenBlueprint("story has no episodes", story=story.public_id)
    for episode in ordered:
        if episode.status == EpisodeStatus.IN_PROGRESS.value:
            return episode
    if story.status == StoryStatus.READY.value and ordered[0].status == EpisodeStatus.PLANNED.value:
        return ordered[0]
    raise BrokenBlueprint(
        "no episode is in progress", story=story.public_id, statuses={item.number: item.status for item in ordered}
    )


def _next_sequence(session: Session, story_id: int) -> int:
    last = session.scalar(
        select(func.max(StoryStateChange.sequence)).where(StoryStateChange.story_id == story_id)
    )
    return (last or 0) + 1


def _resolve_ending(story: Story) -> Ending | None:
    """Lowest ``priority`` wins; priority is the evaluation order, ``position`` is display order."""
    values = {metric.key: metric.current_value for metric in story.metrics}
    for ending in sorted(story.endings, key=lambda item: (item.priority, item.position)):
        if conditions_all_match(ending.conditions, values):
            return ending
    return None


def _change(
    *,
    entity_type: StateChangeEntityType,
    entity_key: str,
    event_type: StateChangeEventType,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "entity_type": entity_type.value,
        "entity_key": entity_key,
        "event_type": event_type.value,
        "before_state": before,
        "after_state": after,
        "source": StateChangeSource.PLAYER.value,
    }


def advance_story(session: Session, public_id: str, choice_key: str) -> PlayOutcome:
    """Apply one choice to a story archive, in one transaction.

    Raises :class:`StoryNotFound`, :class:`StoryFinished`,
    :class:`ChoiceNotInCurrentEpisode` or :class:`NoMatchingEnding`; nothing is
    written when one of them is raised.
    """
    story = session.scalar(
        select(Story)
        .where(Story.public_id == public_id)
        .options(
            selectinload(Story.metrics),
            selectinload(Story.episodes).selectinload(Episode.choices),
            selectinload(Story.endings),
        )
    )
    if story is None:
        raise StoryNotFound("story not found", public_id=public_id)
    if story.status in FINISHED_STATUSES:
        raise StoryFinished("story already finished", status=story.status)

    episode = current_episode(story)
    choice = next((item for item in episode.choices if item.key == choice_key), None)
    if choice is None:
        played = any(
            item.key == choice_key for other in story.episodes for item in other.choices if other is not episode
        )
        raise ChoiceNotInCurrentEpisode(
            "choice does not belong to the episode being played",
            episode=episode.number,
            choice=choice_key,
            already_played=played,
        )

    transaction = session.begin() if not session.in_transaction() else session.begin_nested()
    with transaction:
        sequence = _next_sequence(session, story.id)
        changes: list[dict[str, object]] = []

        if story.status == StoryStatus.READY.value:
            changes.append(
                _change(
                    entity_type=StateChangeEntityType.STORY,
                    entity_key=story.public_id,
                    event_type=StateChangeEventType.STORY_STATUS_CHANGED,
                    before={"status": StoryStatus.READY.value},
                    after={"status": StoryStatus.IN_PROGRESS.value},
                )
            )
            story.status = StoryStatus.IN_PROGRESS.value

        changes.append(
            _change(
                entity_type=StateChangeEntityType.CHOICE,
                entity_key=choice.key,
                event_type=StateChangeEventType.CHOICE_SELECTED,
                before=None,
                after={"episode": episode.number, "text": choice.text},
            )
        )

        metrics = {metric.key: metric for metric in story.metrics}
        for effect in choice.effects:
            metric_key = effect.get("metric_key")
            if metric_key not in metrics:
                # 保存时 BlueprintValidator 已拦过；这里兜底，避免玩到一半抛裸 KeyError。
                raise BrokenBlueprint("choice references an unknown metric", metric=metric_key, choice=choice.key)
            metric = metrics[metric_key]
            before = metric.current_value
            after = clamp_metric(before + int(effect["delta"]))
            metric.current_value = after
            changes.append(
                _change(
                    entity_type=StateChangeEntityType.METRIC,
                    entity_key=metric.key,
                    event_type=StateChangeEventType.METRIC_CHANGED,
                    before={"current_value": before},
                    after={"current_value": after, "delta": int(effect["delta"])},
                )
            )

        previous_status = episode.status
        episode.status = EpisodeStatus.COMPLETED.value
        changes.append(
            _change(
                entity_type=StateChangeEntityType.EPISODE,
                entity_key=str(episode.number),
                event_type=StateChangeEventType.EPISODE_STATUS_CHANGED,
                before={"status": previous_status},
                after={"status": EpisodeStatus.COMPLETED.value},
            )
        )

        next_episode_number: int | None = None
        ending_key: str | None = None
        if episode.number >= story.episode_count:
            ending = _resolve_ending(story)
            if ending is None:
                raise NoMatchingEnding("no ending matches the final metric state", episode=episode.number)
            ending_key = ending.key
            changes.append(
                _change(
                    entity_type=StateChangeEntityType.ENDING,
                    entity_key=ending.key,
                    event_type=StateChangeEventType.ENDING_REACHED,
                    before=None,
                    after={"title": ending.title, "category": ending.category},
                )
            )
            changes.append(
                _change(
                    entity_type=StateChangeEntityType.STORY,
                    entity_key=story.public_id,
                    event_type=StateChangeEventType.STORY_STATUS_CHANGED,
                    before={"status": StoryStatus.IN_PROGRESS.value},
                    after={"status": StoryStatus.COMPLETED.value},
                )
            )
            story.status = StoryStatus.COMPLETED.value
        else:
            upcoming = next((item for item in story.episodes if item.number == episode.number + 1), None)
            if upcoming is None:
                raise BrokenBlueprint(
                    "episode numbers are not contiguous", after=episode.number, count=story.episode_count
                )
            changes.append(
                _change(
                    entity_type=StateChangeEntityType.EPISODE,
                    entity_key=str(upcoming.number),
                    event_type=StateChangeEventType.EPISODE_STATUS_CHANGED,
                    before={"status": upcoming.status},
                    after={"status": EpisodeStatus.IN_PROGRESS.value},
                )
            )
            upcoming.status = EpisodeStatus.IN_PROGRESS.value
            next_episode_number = upcoming.number

        for offset, change in enumerate(changes):
            session.add(StoryStateChange(story=story, sequence=sequence + offset, **change))
        session.flush()

        return PlayOutcome(
            story_public_id=story.public_id,
            story_status=story.status,
            episode_number=episode.number,
            next_episode_number=next_episode_number,
            metrics={key: metric.current_value for key, metric in metrics.items()},
            ending_key=ending_key,
            sequence=sequence + len(changes) - 1,
        )
