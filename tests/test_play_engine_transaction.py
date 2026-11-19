"""回归测试：审查意见指出的「事务内抛错会不会留下脏写」。

审查认为 `begin_nested()` 只回滚 SQL、不回滚内存里已改的 ORM 属性，因此
`NoMatchingEnding` 之后调用方 commit 会把「集已完成、指标已变、结局没写」落库。
这条测试不靠推理，直接读库验证。
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Episode, Metric, Story, StoryStateChange
from app.schemas.story_blueprint import StoryBlueprint
from app.services import play_engine
from app.services.play_engine import NoMatchingEnding, advance_story
from app.services.story_store import save_blueprint
from tests.blueprint_factory import valid_blueprint_data


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

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


def _snapshot(factory: sessionmaker[Session], public_id: str) -> dict[str, object]:
    with factory() as session:
        story = session.scalar(select(Story).where(Story.public_id == public_id))
        metrics = {metric.key: metric.current_value for metric in session.scalars(select(Metric))}
        episodes = {episode.number: episode.status for episode in session.scalars(select(Episode))}
        changes = session.scalar(select(StoryStateChange).where(StoryStateChange.story_id == story.id).with_only_columns(StoryStateChange.id))
        count = len(list(session.scalars(select(StoryStateChange).where(StoryStateChange.story_id == story.id))))
        return {"status": story.status, "metrics": metrics, "episodes": episodes, "changes": count, "_": changes}


def test_no_matching_ending_leaves_no_dirty_write(session_factory: sessionmaker[Session], monkeypatch) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())
    with session_factory() as session:
        public_id = save_blueprint(session, blueprint).public_id
        session.commit()

    # 前两集正常推进，第三集强制「没有任何结局匹配」
    with session_factory() as session:
        advance_story(session, public_id, "e1_truth")
        advance_story(session, public_id, "e2_truth")
        session.commit()

    before = _snapshot(session_factory, public_id)

    monkeypatch.setattr(play_engine, "_resolve_ending", lambda story: None)
    with session_factory() as session:
        _ = session.scalar(select(Story).where(Story.public_id == public_id))  # 触发 autobegin，模拟真实调用方
        with pytest.raises(NoMatchingEnding):
            advance_story(session, public_id, "e3_truth")
        session.commit()  # 关键：调用方照常提交

    after = _snapshot(session_factory, public_id)
    assert after == before, "结局判定失败后不允许留下任何写入"
