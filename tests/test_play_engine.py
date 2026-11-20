"""Player-choice executor tests.

These pin the promise the product rests on: the same choice always produces the
same number, and the same metric state always picks the same ending. The model
never decides arithmetic, so every assertion here is exact.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Choice, Ending, Episode, Metric, Story, StoryStateChange, StoryStatus
from app.schemas.story_blueprint import StoryBlueprint
from app.services.conditions import conditions_all_match
from app.services.play_engine import (
    BrokenBlueprint,
    ChoiceNotInCurrentEpisode,
    NoMatchingEnding,
    StoryFinished,
    StoryNotFound,
    advance_story,
)
from app.services.story_store import save_blueprint
from tests.blueprint_factory import valid_blueprint_data


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _save(factory: sessionmaker[Session], data: dict | None = None) -> str:
    blueprint = StoryBlueprint.model_validate(data or valid_blueprint_data())
    with factory() as session:
        return save_blueprint(session, blueprint).public_id


def _metric_values(factory: sessionmaker[Session], public_id: str) -> dict[str, int]:
    with factory() as session:
        metrics = session.scalars(
            select(Metric).join(Metric.story).where(Metric.story.has(public_id=public_id))
        )
        return {metric.key: metric.current_value for metric in metrics}


def _changes(factory: sessionmaker[Session], public_id: str) -> list[StoryStateChange]:
    with factory() as session:
        return list(
            session.scalars(
                select(StoryStateChange)
                .join(StoryStateChange.story)
                .where(StoryStateChange.story.has(public_id=public_id))
                .order_by(StoryStateChange.sequence)
            )
        )


def test_first_choice_starts_the_story_and_applies_effects(
    session_factory: sessionmaker[Session],
) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        outcome = advance_story(session, public_id, "e1_truth")
        session.commit()

    assert outcome.story_status == StoryStatus.IN_PROGRESS.value
    assert outcome.episode_number == 1
    assert outcome.next_episode_number == 2
    assert outcome.ending_key is None
    assert outcome.metrics == {"reputation": 62, "mindset": 50}

    with session_factory() as session:
        episodes = {
            episode.number: episode.status
            for episode in session.scalars(select(Episode).order_by(Episode.number))
        }
    assert episodes[1] == "completed"
    assert episodes[2] == "in_progress"
    assert episodes[3] == "planned"


def test_every_mutation_is_appended_to_the_event_log(
    session_factory: sessionmaker[Session],
) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        advance_story(session, public_id, "e1_traffic")
        session.commit()

    events = [(change.sequence, change.event_type, change.entity_type) for change in _changes(session_factory, public_id)]
    created = events[0]
    assert created == (1, "story_created", "story"), "save 时写入的首条事件必须保持 sequence 1"

    rest = events[1:]
    assert [sequence for sequence, _, _ in rest] == list(range(2, 2 + len(rest))), "序列号必须连续"
    assert ("story_status_changed", "story") in [(event, entity) for _, event, entity in rest]
    assert ("choice_selected", "choice") in [(event, entity) for _, event, entity in rest]
    assert ("metric_changed", "metric") in [(event, entity) for _, event, entity in rest]
    assert rest[-1][1] == "episode_status_changed"

    metric_rows = [change for change in _changes(session_factory, public_id) if change.event_type == "metric_changed"]
    before_after = {(
        row.entity_key,
        (row.before_state or {})["current_value"],
        (row.after_state or {})["current_value"],
    ) for row in metric_rows}
    assert before_after == {("reputation", 50, 42), ("mindset", 50, 45)}
    assert all(row.source == "player" for row in metric_rows)


def test_three_truth_choices_reach_the_high_ending(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        for episode, choice in [(1, "e1_truth"), (2, "e2_truth"), (3, "e3_truth")]:
            outcome = advance_story(session, public_id, choice)
            assert outcome.episode_number == episode
        session.commit()

    assert outcome.story_status == StoryStatus.COMPLETED.value
    assert outcome.next_episode_number is None
    assert outcome.metrics == {"reputation": 86, "mindset": 50}
    assert outcome.ending_key == "comeback", "≥70 应命中高口碑结局"

    final_events = [change.event_type for change in _changes(session_factory, public_id)]
    assert "ending_reached" in final_events


def test_three_traffic_choices_reach_the_low_ending(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        for choice in ("e1_traffic", "e2_traffic", "e3_traffic"):
            outcome = advance_story(session, public_id, choice)
        session.commit()

    assert outcome.metrics == {"reputation": 26, "mindset": 35}
    assert outcome.ending_key == "quit", "<30 应命中低口碑结局"


def test_mixed_choices_land_on_the_middle_ending(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        for choice in ("e1_truth", "e2_truth", "e3_traffic"):
            outcome = advance_story(session, public_id, choice)
        session.commit()

    assert outcome.metrics == {"reputation": 66, "mindset": 45}
    assert outcome.ending_key == "survive", "30≤rep<70 应命中中间结局"


def test_replaying_a_choice_from_a_finished_episode_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        advance_story(session, public_id, "e1_truth")
        session.commit()

    with session_factory() as session, pytest.raises(ChoiceNotInCurrentEpisode) as raised:
        advance_story(session, public_id, "e1_truth")
        session.commit()

    assert raised.value.details["episode"] == 2
    assert raised.value.details["already_played"] is True

    with session_factory() as session:
        story_metrics = session.scalars(select(Metric).order_by(Metric.key)).all()
    assert {metric.key: metric.current_value for metric in story_metrics} == {"mindset": 50, "reputation": 62}, (
        "被拒绝的选择不能产生任何写入"
    )


def test_unknown_choice_is_rejected_without_writes(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)
    before = len(_changes(session_factory, public_id))

    with session_factory() as session, pytest.raises(ChoiceNotInCurrentEpisode) as raised:
        advance_story(session, public_id, "no_such_choice")
        session.commit()

    assert raised.value.details["already_played"] is False
    assert len(_changes(session_factory, public_id)) == before


def test_finished_story_rejects_further_choices(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)

    with session_factory() as session:
        for choice in ("e1_truth", "e2_truth", "e3_truth"):
            advance_story(session, public_id, choice)
        session.commit()

    with session_factory() as session, pytest.raises(StoryFinished):
        advance_story(session, public_id, "e3_truth")


def test_unknown_story_raises_not_found(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session, pytest.raises(StoryNotFound):
        advance_story(session, "does-not-exist", "e1_truth")


def test_metric_change_is_clamped_to_the_database_range(
    session_factory: sessionmaker[Session],
) -> None:
    data = valid_blueprint_data()
    data["metrics"][0]["initial_value"] = 95
    public_id = _save(session_factory, data)

    with session_factory() as session:
        outcome = advance_story(session, public_id, "e1_truth")
        session.commit()

    assert outcome.metrics["reputation"] == 100, "95+12 必须夹到 100，否则 CHECK 约束会拒绝写入"
    assert _metric_values(session_factory, public_id)["reputation"] == 100


def test_conditions_match_identically_for_dataclass_and_json_dict() -> None:
    """校验器用 dataclass、执行器读 ORM 的 JSON dict，两套词汇必须给同一个答案。"""
    from app.schemas.story_blueprint import EndingCondition

    dataclass_conditions = [
        EndingCondition(metric_id="reputation", operator="gte", value=70),
        EndingCondition(metric_id="mindset", operator="lt", value=40),
    ]
    json_conditions = [
        {"metric_key": "reputation", "operator": "gte", "value": 70},
        {"metric_key": "mindset", "operator": "lt", "value": 40},
    ]

    for values, expected in [
        ({"reputation": 70, "mindset": 39}, True),
        ({"reputation": 69, "mindset": 39}, False),
        ({"reputation": 90, "mindset": 40}, False),
        ({"reputation": 90}, False),  # 指标缺失 → 条件不成立，不崩
    ]:
        assert conditions_all_match(dataclass_conditions, values) is expected
        assert conditions_all_match(json_conditions, values) is expected


def test_choice_effect_referencing_unknown_metric_is_a_play_error(
    session_factory: sessionmaker[Session],
) -> None:
    """保存时校验器已拦过；手工改库绕过校验时，引擎要给 PlayError 而不是裸 KeyError。"""
    public_id = _save(session_factory)
    with session_factory() as session:
        choice = session.scalars(select(Choice).where(Choice.key == "e1_truth")).one()
        choice.effects = [{"metric_key": "ghost_metric", "delta": 5}]
        session.commit()

    with session_factory() as session, pytest.raises(BrokenBlueprint) as raised:
        advance_story(session, public_id, "e1_truth")

    assert raised.value.details["metric"] == "ghost_metric"


def test_ending_condition_referencing_unknown_metric_finds_no_ending(
    session_factory: sessionmaker[Session],
) -> None:
    public_id = _save(session_factory)
    with session_factory() as session:
        for ending in session.scalars(select(Ending)):
            ending.conditions = [{"metric_key": "ghost_metric", "operator": "gte", "value": 1}]
        session.commit()

    with session_factory() as session:
        advance_story(session, public_id, "e1_truth")
        advance_story(session, public_id, "e2_truth")
        session.commit()

    with session_factory() as session, pytest.raises(NoMatchingEnding):
        advance_story(session, public_id, "e3_truth")


def test_story_claiming_progress_with_no_active_episode_is_rejected(
    session_factory: sessionmaker[Session],
) -> None:
    """所有集都是 planned 但故事状态是 in_progress，属于坏数据，不该被当成第 1 集重开。"""
    public_id = _save(session_factory)
    with session_factory() as session:
        story = session.scalars(select(Story).where(Story.public_id == public_id)).one()
        story.status = StoryStatus.IN_PROGRESS.value
        session.commit()

    with session_factory() as session, pytest.raises(BrokenBlueprint):
        advance_story(session, public_id, "e1_truth")


def test_persisted_ending_with_unknown_operator_is_not_a_crash(
    session_factory: sessionmaker[Session],
) -> None:
    """手工把 operator 改成 ne：应当当作「条件不成立」，最终报没有结局匹配，而不是裸 KeyError。"""
    public_id = _save(session_factory)
    with session_factory() as session:
        for ending in session.scalars(select(Ending)):
            ending.conditions = [{"metric_key": "reputation", "operator": "ne", "value": 1}]
        session.commit()

    with session_factory() as session:
        advance_story(session, public_id, "e1_truth")
        advance_story(session, public_id, "e2_truth")
        session.commit()

    with session_factory() as session, pytest.raises(NoMatchingEnding):
        advance_story(session, public_id, "e3_truth")


def test_choice_effect_without_delta_is_a_play_error(session_factory: sessionmaker[Session]) -> None:
    public_id = _save(session_factory)
    with session_factory() as session:
        choice = session.scalars(select(Choice).where(Choice.key == "e1_truth")).one()
        choice.effects = [{"metric_key": "reputation"}]
        session.commit()

    with session_factory() as session, pytest.raises(BrokenBlueprint) as raised:
        advance_story(session, public_id, "e1_truth")

    assert raised.value.details["choice"] == "e1_truth"
