"""回归测试：「结局判定失败时不留任何写入」到底成不成立。

审查两次判定这是脏写风险：`begin_nested()` 只回滚 SQL、不回滚内存里的 ORM 属性，
调用方随后 commit 会把已改的指标与集状态落库。

这里不靠推理，也不靠换 session「绕过」identity map：在**同一个 session** 上
commit 之后，先读 ORM 对象属性（若属性没被 expire，这里就会看到脏值），再直接查库。
两条路径都断言与失败前完全一致。
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


def _committed_state(factory: sessionmaker[Session], public_id: str) -> dict:
    """Read the committed truth in a fresh session: statuses, metrics, and the number of events."""
    with factory() as session:
        story = session.scalars(select(Story).where(Story.public_id == public_id)).one()
        return {
            "story_status": story.status,
            "metrics": {metric.key: metric.current_value for metric in session.scalars(select(Metric))},
            "episodes": {episode.number: episode.status for episode in session.scalars(select(Episode))},
            "events": len(list(session.scalars(select(StoryStateChange)))),
        }


def test_no_matching_ending_leaves_no_write_in_the_committing_session(
    session_factory: sessionmaker[Session], monkeypatch
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())
    with session_factory() as session:
        public_id = save_blueprint(session, blueprint).public_id
        session.commit()

    with session_factory() as session:
        advance_story(session, public_id, "e1_truth")
        advance_story(session, public_id, "e2_truth")
        session.commit()

    before = _committed_state(session_factory, public_id)
    monkeypatch.setattr(play_engine, "_resolve_ending", lambda story: None)

    with session_factory() as session:
        story = session.scalars(select(Story).where(Story.public_id == public_id)).one()  # 触发 autobegin
        assert session.in_transaction() is True, "真实调用方总是已经处于事务中，这正是争议场景"

        with pytest.raises(NoMatchingEnding):
            advance_story(session, public_id, "e3_truth")

        # 第一处断言：不换 session、不 commit，直接读内存里的属性。
        # 若 savepoint 没 expire 被改对象，这里会看到 dirty 值。
        assert story.status == "in_progress"
        assert {episode.number: episode.status for episode in session.scalars(select(Episode))}[3] == "in_progress"
        assert {metric.key: metric.current_value for metric in session.scalars(select(Metric))} == {
            "mindset": 50,
            "reputation": 74,
        }

        session.commit()  # 关键：调用方照常提交

    # 第二处断言：落库的真实状态
    assert _committed_state(session_factory, public_id) == before
