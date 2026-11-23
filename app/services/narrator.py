"""Turn one player event into cached narration text.

Division of labour
------------------
``load_context`` reads the archive and builds a *redacted* view of the turn:
character names and roles only, never ``secret``; metric changes as semantic
phrases, never values. :mod:`app.prompts.narration` renders that view. This
module owns the model call, the repair loop, and the one-write cache.

The cache is the point of the batch: a replay of an event the archive has
already narrated must not call the provider at all. The unique
``(story_id, sequence)`` constraint backs that up under concurrency — the loser
of an insert race reads the winner's row instead of failing the request.

One play action writes several player-event rows, so the cache key is the
*turn anchor* — the sequence of that turn's ``choice_selected`` row — not the
sequence the caller asked for. Otherwise one turn would be narrated once per
row: several model calls, several rows, several different texts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.blueprint_contract import BLUEPRINT_VERSION, version_is_supported
from app.clients.deepseek import LlmReply
from app.models import (
    Episode,
    Narration,
    StateChangeEventType,
    StateChangeSource,
    Story,
    StoryStateChange,
)
from app.prompts.narration import build_messages, repair_messages
from app.request_context import get_request_id
from app.services.story_store import BlueprintVersionError

logger = logging.getLogger(__name__)

MIN_NARRATION_HANZI = 120
MAX_NARRATION_HANZI = 400


class CompletionClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> LlmReply: ...


class NarrationStoryNotFound(RuntimeError):
    """There is no archive with this public id."""


class NarrationEventNotFound(RuntimeError):
    """The sequence is out of range or is not a narratable player event."""


class NarrationRejected(RuntimeError):
    """The model never produced acceptable narration within the attempt budget."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        issues: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.issues = list(issues or [])


@dataclass(frozen=True)
class CharacterBrief:
    """What the narrator may know about a character: a name and a role."""

    name: str
    role: str


@dataclass(frozen=True)
class MetricShift:
    """One metric change expressed only as a phrase a player can read."""

    name: str
    description: str


@dataclass(frozen=True)
class NarrationContext:
    """The redacted, prompt-ready description of one player turn."""

    # Internal id, needed to address the narration row. Never rendered.
    story_id: int
    # The cache key and the ``sequence`` we return to the client: the
    # ``choice_selected`` row of the turn this context describes. Every player
    # row written by one play action maps onto this single anchor.
    turn_sequence: int
    title: str
    genre: str
    theme: str
    episode_number: int
    episode_objective: str
    episode_conflict: str
    characters: tuple[CharacterBrief, ...]
    choice_text: str
    consequence_hint: str
    metric_shifts: tuple[MetricShift, ...]


def _count_hanzi(text: str) -> int:
    return sum(1 for character in text if "一" <= character <= "鿿")


def _looks_like_json(text: str) -> bool:
    """True when the reply is (or claims to be) a JSON document."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in "{[":
        return True
    try:
        json.loads(stripped)
    except (TypeError, ValueError):
        return False
    return True


def validate_narration(text: str) -> list[str]:
    """Return every reason ``text`` cannot be shown to a player; empty is valid.

    Kept free of database and model access so the rules are directly testable
    and the repair loop can hand the same strings back to the model.
    """
    stripped = text.strip()
    issues: list[str] = []

    if "```" in stripped:
        issues.append("不要使用 Markdown 代码围栏，只输出纯文本")
    if _looks_like_json(stripped):
        issues.append("不要返回 JSON，只输出一段中文旁白")

    hanzi = _count_hanzi(stripped)
    if hanzi < MIN_NARRATION_HANZI:
        issues.append(
            f"旁白过短：只有 {hanzi} 个汉字，至少需要 {MIN_NARRATION_HANZI} 个"
        )
    elif hanzi > MAX_NARRATION_HANZI:
        issues.append(
            f"旁白过长：有 {hanzi} 个汉字，最多允许 {MAX_NARRATION_HANZI} 个"
        )

    return issues


def _describe_metric_shift(name: str, delta: int) -> str:
    """Turn an internal delta into a phrase such as ``观众口碑明显上升``."""
    if delta == 0:
        return f"{name}基本没有变化"
    magnitude = abs(delta)
    if magnitude >= 10:
        degree = "明显"
    elif magnitude >= 4:
        degree = "有所"
    else:
        degree = "略有"
    direction = "上升" if delta > 0 else "下降"
    return f"{name}{degree}{direction}"


def load_context(
    session: Session,
    public_id: str,
    sequence: int,
) -> NarrationContext | None:
    """Build the prompt context for one event, or return ``None``.

    ``None`` means either the archive is missing or the sequence is not a
    player event; :func:`generate` distinguishes the two for the HTTP contract.
    An archive whose blueprint version this server cannot interpret raises
    :class:`BlueprintVersionError`, exactly like the detail and play paths.
    """
    story = session.scalar(
        select(Story)
        .where(Story.public_id == public_id)
        .options(
            selectinload(Story.characters),
            selectinload(Story.metrics),
            selectinload(Story.episodes).selectinload(Episode.choices),
        )
    )
    if story is None:
        return None
    if not version_is_supported(story.blueprint_version):
        raise BlueprintVersionError(
            stored=story.blueprint_version,
            supported=BLUEPRINT_VERSION,
        )

    event = session.scalar(
        select(StoryStateChange).where(
            StoryStateChange.story_id == story.id,
            StoryStateChange.sequence == sequence,
        )
    )
    # ``story_created`` and administrative rows are not player actions, so
    # there is no choice to narrate.
    if event is None or event.source != StateChangeSource.PLAYER.value:
        return None

    choice_event = session.scalar(
        select(StoryStateChange)
        .where(
            StoryStateChange.story_id == story.id,
            StoryStateChange.event_type
            == StateChangeEventType.CHOICE_SELECTED.value,
            StoryStateChange.sequence <= sequence,
        )
        .order_by(StoryStateChange.sequence.desc())
        .limit(1)
    )
    if choice_event is None:
        # The first turn writes ``story_status_changed`` before
        # ``choice_selected``. That row is still a player event belonging to
        # the turn, so anchor it on the following choice instead of reporting
        # an event that plainly exists as not narratable.
        choice_event = session.scalar(
            select(StoryStateChange)
            .where(
                StoryStateChange.story_id == story.id,
                StoryStateChange.event_type
                == StateChangeEventType.CHOICE_SELECTED.value,
                StoryStateChange.sequence > sequence,
            )
            .order_by(StoryStateChange.sequence)
            .limit(1)
        )
    if choice_event is None:
        return None

    after_choice = choice_event.after_state or {}
    try:
        episode_number = int(after_choice["episode"])
    except (KeyError, TypeError, ValueError):
        return None
    episode = next(
        (item for item in story.episodes if item.number == episode_number),
        None,
    )
    if episode is None:
        return None
    choice = next(
        (item for item in episode.choices if item.key == choice_event.entity_key),
        None,
    )
    if choice is None:
        return None

    # One play action writes several rows. Bound this turn's metric changes by
    # the next ``choice_selected`` so a later turn cannot leak into this text.
    next_choice_sequence = session.scalar(
        select(func.min(StoryStateChange.sequence)).where(
            StoryStateChange.story_id == story.id,
            StoryStateChange.event_type
            == StateChangeEventType.CHOICE_SELECTED.value,
            StoryStateChange.sequence > choice_event.sequence,
        )
    )
    metric_statement = (
        select(StoryStateChange)
        .where(
            StoryStateChange.story_id == story.id,
            StoryStateChange.event_type
            == StateChangeEventType.METRIC_CHANGED.value,
            StoryStateChange.sequence > choice_event.sequence,
        )
        .order_by(StoryStateChange.sequence)
    )
    if next_choice_sequence is not None:
        metric_statement = metric_statement.where(
            StoryStateChange.sequence < next_choice_sequence
        )
    metric_changes = list(session.scalars(metric_statement))

    metrics_by_key = {metric.key: metric for metric in story.metrics}
    shifts: list[MetricShift] = []
    for change in metric_changes:
        metric = metrics_by_key.get(change.entity_key)
        if metric is None:
            continue
        delta = (change.after_state or {}).get("delta")
        if not isinstance(delta, int) or isinstance(delta, bool):
            continue
        shifts.append(
            MetricShift(
                name=metric.name,
                description=_describe_metric_shift(metric.name, delta),
            )
        )

    return NarrationContext(
        story_id=story.id,
        turn_sequence=choice_event.sequence,
        title=story.title,
        genre=story.genre,
        theme=story.theme,
        episode_number=episode.number,
        episode_objective=episode.objective,
        episode_conflict=episode.conflict,
        # Name and role only: ``secret`` must never reach a prompt.
        characters=tuple(
            CharacterBrief(name=character.name, role=character.role)
            for character in story.characters
        ),
        choice_text=str(after_choice.get("text") or choice.text),
        consequence_hint=choice.consequence_hint,
        metric_shifts=tuple(shifts),
    )


def _find_cached(
    session: Session, story_id: int, sequence: int
) -> Narration | None:
    return session.scalar(
        select(Narration).where(
            Narration.story_id == story_id,
            Narration.sequence == sequence,
        )
    )


def _story_exists(session: Session, public_id: str) -> bool:
    return (
        session.scalar(select(Story.id).where(Story.public_id == public_id))
        is not None
    )


async def generate(
    session: Session,
    public_id: str,
    sequence: int,
    *,
    client: CompletionClient,
    max_attempts: int = 3,
) -> Narration:
    """Return the cached narration or generate, validate, and store one.

    ``sequence`` only selects the player event; the narration is keyed by the
    turn anchor in ``context.turn_sequence``, so every row of one play action
    reads and writes the same cache entry.

    Raises :class:`NarrationStoryNotFound`, :class:`NarrationEventNotFound`,
    :class:`BlueprintVersionError`, :class:`NarrationRejected`, or whatever the
    client raises. A rejected generation writes nothing.
    """
    context = load_context(session, public_id, sequence)
    if context is None:
        if _story_exists(session, public_id):
            raise NarrationEventNotFound("this event has no narration")
        raise NarrationStoryNotFound("story not found")

    # Must stay ahead of the model call: a replay is the whole point of the
    # cache. ``load_context`` still ran so a missing story, a missing event, or
    # an unsupported archive version still surfaces with its own error.
    cached = _find_cached(session, context.story_id, context.turn_sequence)
    if cached is not None:
        return cached

    base_messages = build_messages(context)
    messages = base_messages
    issues: list[str] = []
    for attempt in range(1, max_attempts + 1):
        reply = await client.complete(messages)
        issues = validate_narration(reply.content)
        if issues:
            if attempt < max_attempts:
                messages = repair_messages(base_messages, reply.content, issues)
            continue

        narration = Narration(
            story_id=context.story_id,
            sequence=context.turn_sequence,
            text=reply.content.strip(),
            model=reply.model,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
        )
        try:
            session.add(narration)
            session.commit()
        except IntegrityError:
            # Another request stored this turn first. Its text is the one the
            # player should see; replaying ours would mean two different
            # narratives for one event.
            session.rollback()
            existing = _find_cached(
                session, context.story_id, context.turn_sequence
            )
            if existing is None:
                raise
            return existing

        logger.info(
            "narration success request_id=%s story_id=%s sequence=%s model=%s "
            "attempts=%s prompt_tokens=%s completion_tokens=%s",
            get_request_id(),
            context.story_id,
            context.turn_sequence,
            reply.model,
            attempt,
            reply.prompt_tokens,
            reply.completion_tokens,
        )
        return narration

    logger.warning(
        "narration rejected request_id=%s story_id=%s sequence=%s attempts=%s "
        "issue_count=%s issues=%s",
        get_request_id(),
        context.story_id,
        context.turn_sequence,
        max_attempts,
        len(issues),
        " | ".join(issues),
    )
    raise NarrationRejected(
        "narration failed validation",
        attempts=max_attempts,
        issues=issues,
    )
