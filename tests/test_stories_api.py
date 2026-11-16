import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.db import create_db_engine
from app.dependencies import get_db_session, get_story_planner
from app.main import create_app
from app.models import (
    Base,
    Character,
    Choice,
    Ending,
    Episode,
    Metric,
    Story,
    StoryStateChange,
)
from app.schemas.story_blueprint import StoryBlueprint
from app.services.story_planner import StoryPlanner, StoryPlanningError
from app.services.story_store import (
    BlueprintStorageError,
    list_stories,
    load_blueprint,
    save_blueprint,
)
from tests.blueprint_factory import valid_blueprint_data


class FakeClient:
    async def complete(self, messages: list[dict[str, str]]) -> LlmReply:
        return LlmReply(
            json.dumps(valid_blueprint_data(), ensure_ascii=False),
            "fake-model",
            4,
            8,
        )


class FailingPlanner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def plan(self, inspiration: str, episode_count: int):
        raise self.error


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


@pytest.fixture
def api_client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_story_planner] = lambda: StoryPlanner(FakeClient())
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _row_count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_database_engine_enables_foreign_keys_for_each_sqlite_connection() -> None:
    engine = create_db_engine("sqlite://")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()


def test_save_and_load_blueprint_round_trip_includes_entire_tree(
    session_factory: sessionmaker[Session],
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        story = save_blueprint(session, blueprint)
        public_id = story.public_id
        counts = {
            Story: _row_count(session, Story),
            Character: _row_count(session, Character),
            Metric: _row_count(session, Metric),
            Episode: _row_count(session, Episode),
            Choice: _row_count(session, Choice),
            Ending: _row_count(session, Ending),
            StoryStateChange: _row_count(session, StoryStateChange),
        }

    assert counts == {
        Story: 1,
        Character: 2,
        Metric: 2,
        Episode: 3,
        Choice: 6,
        Ending: 3,
        StoryStateChange: 1,
    }

    with session_factory() as session:
        restored = load_blueprint(session, public_id)

    assert restored is not None
    assert restored.model_dump() == blueprint.model_dump()
    assert restored.title == blueprint.title
    assert [character.id for character in restored.characters] == ["anchor", "rival"]
    assert [metric.id for metric in restored.metrics] == ["reputation", "mindset"]
    assert [
        (episode.number, [choice.id for choice in episode.choices])
        for episode in restored.episodes
    ] == [
        (1, ["e1_truth", "e1_traffic"]),
        (2, ["e2_truth", "e2_traffic"]),
        (3, ["e3_truth", "e3_traffic"]),
    ]
    assert [ending.id for ending in restored.endings] == [
        "quit",
        "comeback",
        "survive",
    ]


def test_blueprint_round_trip_preserves_endings_array_order(
    session_factory: sessionmaker[Session],
) -> None:
    data = valid_blueprint_data()
    data["endings"] = [
        data["endings"][1],
        data["endings"][0],
        data["endings"][2],
    ]
    blueprint = StoryBlueprint.model_validate(data)
    assert [ending.priority for ending in blueprint.endings] == [2, 1, 3]

    with session_factory() as session:
        story = save_blueprint(session, blueprint)
        public_id = story.public_id

    with session_factory() as session:
        restored = load_blueprint(session, public_id)

    assert restored is not None
    assert restored.model_dump() == blueprint.model_dump()
    assert [ending.id for ending in restored.endings] == [
        "comeback",
        "quit",
        "survive",
    ]


def test_save_blueprint_rolls_back_mid_transaction(
    session_factory: sessionmaker[Session],
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:

        def fail_after_flush(db_session, flush_context) -> None:
            raise RuntimeError("forced failure after rows were flushed")

        event.listen(session, "after_flush_postexec", fail_after_flush, once=True)
        with pytest.raises(RuntimeError, match="forced failure"):
            save_blueprint(session, blueprint)

    with session_factory() as session:
        counts = {
            model.__tablename__: _row_count(session, model)
            for model in (
                Story,
                Character,
                Metric,
                Episode,
                Choice,
                Ending,
                StoryStateChange,
            )
        }

    assert counts == {
        "stories": 0,
        "characters": 0,
        "metrics": 0,
        "episodes": 0,
        "choices": 0,
        "endings": 0,
        "story_state_changes": 0,
    }


def test_saving_same_blueprint_twice_creates_two_archives(
    session_factory: sessionmaker[Session],
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        first = save_blueprint(session, blueprint)
        second = save_blueprint(session, blueprint)
        public_ids = (first.public_id, second.public_id)

    assert public_ids[0] != public_ids[1]
    with session_factory() as session:
        assert _row_count(session, Story) == 2
        assert _row_count(session, Episode) == 6
        assert _row_count(session, StoryStateChange) == 2


def test_invalid_blueprint_is_rejected_before_any_rows_are_written(
    session_factory: sessionmaker[Session],
) -> None:
    data = valid_blueprint_data()
    data["metrics"] = data["metrics"][:1] + [
        {
            **data["metrics"][1],
            "id": "reputation_2",
        }
    ]
    blueprint = StoryBlueprint.model_validate(data)
    blueprint.metrics[1].id = "mindset"

    with session_factory() as session:
        invalid_effect = blueprint.episodes[0].choices[0].effects[0]
        invalid_effect.metric_id = "unknown_metric"
        with pytest.raises(BlueprintStorageError, match="cannot be stored"):
            save_blueprint(session, blueprint)

    with session_factory() as session:
        assert _row_count(session, Story) == 0


def test_create_restore_and_list_story_archives(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == 201
    created = response.json()["data"]
    assert created["public_id"]
    assert created["title"] == "麦克风没有关"
    assert created["status"] == "ready"
    assert "characters" not in created

    with session_factory() as session:
        assert _row_count(session, Story) == 1
        assert _row_count(session, Choice) == 6

    detail = api_client.get(f"/api/stories/{created['public_id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["public_id"] == created["public_id"]
    assert detail.json()["data"]["blueprint"] == valid_blueprint_data()

    listing = api_client.get("/api/stories", params={"offset": 0, "limit": 20})
    assert listing.status_code == 200
    listed = listing.json()["data"]
    assert listed["total"] == 1
    assert listed["offset"] == 0
    assert listed["limit"] == 20
    assert len(listed["items"]) == 1
    assert listed["items"][0]["public_id"] == created["public_id"]
    assert "blueprint" not in listed["items"][0]
    assert "episodes" not in listed["items"][0]


def test_list_stories_supports_pagination(
    session_factory: sessionmaker[Session],
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())
    with session_factory() as session:
        for _ in range(3):
            save_blueprint(session, blueprint)

    with session_factory() as session:
        page, total = list_stories(session, offset=1, limit=1)

    assert total == 3
    assert len(page) == 1


def test_get_missing_story_returns_404(api_client: TestClient) -> None:
    response = api_client.get("/api/stories/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "code": 40401,
        "message": "story not found",
        "data": None,
    }


def test_get_story_state_returns_persisted_play_progress(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        story = session.scalar(select(Story).where(Story.public_id == created["public_id"]))
        assert story is not None
        reputation = next(metric for metric in story.metrics if metric.key == "reputation")
        first_episode = next(episode for episode in story.episodes if episode.number == 1)

        story.status = "in_progress"
        reputation.current_value = 7
        first_episode.status = "completed"
        session.add(
            StoryStateChange(
                story=story,
                sequence=2,
                entity_type="metric",
                entity_key="reputation",
                event_type="metric_changed",
                before_state={"current_value": 50},
                after_state={"current_value": 7},
                source="player",
            )
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}/state")

    assert response.status_code == 200
    state = response.json()["data"]
    assert state["public_id"] == created["public_id"]
    assert state["status"] == "in_progress"
    assert state["metrics"] == [
        {"metric_id": "reputation", "current_value": 7},
        {"metric_id": "mindset", "current_value": 50},
    ]
    assert state["episodes"] == [
        {"number": 1, "status": "completed"},
        {"number": 2, "status": "planned"},
        {"number": 3, "status": "planned"},
    ]
    assert state["last_sequence"] == 2
    assert [change["sequence"] for change in state["recent_state_changes"]] == [2, 1]
    assert state["recent_state_changes"][0]["after_state"] == {"current_value": 7}
    assert "blueprint" not in state

    limited = api_client.get(
        f"/api/stories/{created['public_id']}/state",
        params={"change_limit": 1},
    ).json()["data"]
    assert [change["sequence"] for change in limited["recent_state_changes"]] == [2]

    blueprint = api_client.get(f"/api/stories/{created['public_id']}").json()["data"][
        "blueprint"
    ]
    assert blueprint["metrics"][0]["initial_value"] == 50


def test_get_missing_story_state_returns_404(api_client: TestClient) -> None:
    response = api_client.get("/api/stories/does-not-exist/state")

    assert response.status_code == 404
    assert response.json() == {
        "code": 40401,
        "message": "story not found",
        "data": None,
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_message"),
    [
        (
            DeepSeekClientError("auth failed", retryable=False, status_code=401),
            503,
            50302,
            "story model credentials were rejected",
        ),
        (
            DeepSeekClientError("payment required", retryable=False, status_code=402),
            503,
            50303,
            "story model account has insufficient balance",
        ),
        (
            DeepSeekClientError("bad content", retryable=True, status_code=200),
            422,
            42201,
            "unable to create a valid story plan",
        ),
        (
            DeepSeekClientError("bad request", retryable=False, status_code=400),
            400,
            50202,
            "story model rejected the request",
        ),
        (
            DeepSeekClientError("redirect", retryable=False, status_code=302),
            502,
            50204,
            "story model returned an unexpected protocol status",
        ),
        (
            DeepSeekClientError("timeout", retryable=True, status_code=None),
            502,
            50201,
            "story model is temporarily unavailable",
        ),
        (
            StoryPlanningError("invalid blueprint", attempts=3),
            422,
            42201,
            "unable to create a valid story plan",
        ),
    ],
)
def test_create_story_preserves_planning_error_contract(
    session_factory: sessionmaker[Session],
    error: Exception,
    expected_status: int,
    expected_code: int,
    expected_message: str,
) -> None:
    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_story_planner] = lambda: FailingPlanner(error)
    try:
        response = TestClient(app).post(
            "/api/stories",
            json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["message"] == expected_message


def test_story_endpoints_are_present_in_openapi(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()
    paths = schema["paths"]

    assert paths["/api/stories"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/StoryCreatedResponse")
    assert paths["/api/stories"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/StoryListResponse")
    assert paths["/api/stories/{public_id}"]["get"]["responses"]["404"]
    assert paths["/api/stories/{public_id}/state"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith("/StoryStateResponse")
