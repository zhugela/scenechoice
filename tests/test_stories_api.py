import asyncio
import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.stories import create_story
from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.db import create_db_engine
from app.dependencies import get_db_session, get_story_planner
from app.errors import AppError
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
from app.models.base import as_utc
from app.schemas.stories import CreateStoryRequest
from app.schemas.story_blueprint import StoryBlueprint
from app.services.story_planner import StoryPlanner, StoryPlanningError
from app.services.story_store import (
    BLUEPRINT_VERSION,
    BlueprintStorageError,
    list_stories,
    load_blueprint,
    save_blueprint,
)
from tests.blueprint_factory import valid_blueprint_data


class FakeClient:
    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> LlmReply:
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
            DeepSeekClientError("forbidden", retryable=False, status_code=403),
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
            DeepSeekClientError("request timeout", retryable=True, status_code=408),
            502,
            50201,
            "story model is temporarily unavailable",
        ),
        (
            DeepSeekClientError("rate limited", retryable=True, status_code=429),
            502,
            50201,
            "story model is temporarily unavailable",
        ),
        (
            DeepSeekClientError("provider failed", retryable=True, status_code=500),
            502,
            50201,
            "story model is temporarily unavailable",
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


def test_create_story_keeps_provider_error_in_the_exception_chain(
    session_factory: sessionmaker[Session],
) -> None:
    provider_error = DeepSeekClientError("auth failed", retryable=False, status_code=401)
    request = CreateStoryRequest(
        inspiration="一个小主播误开麦后被恶意剪辑",
        episode_count=3,
    )

    with session_factory() as session:
        with pytest.raises(AppError) as raised:
            asyncio.run(create_story(request, FailingPlanner(provider_error), session))

    assert raised.value.code == 50302
    assert raised.value.__cause__ is provider_error


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


def test_save_blueprint_writes_explicit_blueprint_version(
    session_factory: sessionmaker[Session],
) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        story = save_blueprint(session, blueprint)
        public_id = story.public_id

    with session_factory() as session:
        stored_version = session.scalar(
            text(
                "SELECT blueprint_version FROM stories WHERE public_id = :public_id"
            ),
            {"public_id": public_id},
        )

    assert BLUEPRINT_VERSION == 1
    assert stored_version == BLUEPRINT_VERSION


def test_get_story_with_unsupported_blueprint_version_returns_409_40902(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        session.execute(
            text(
                "UPDATE stories SET blueprint_version = 0 "
                "WHERE public_id = :public_id"
            ),
            {"public_id": created["public_id"]},
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}")

    body = response.json()
    assert response.status_code == 409
    assert body["code"] == 40902
    assert body["message"] != "internal server error"
    assert "blueprint version 0" in body["message"]
    assert "supports version 1" in body["message"]


def test_get_story_with_corrupted_blueprint_returns_500_50003(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        session.execute(
            text(
                "UPDATE characters SET personality = :personality "
                "WHERE story_id = "
                "(SELECT id FROM stories WHERE public_id = :public_id) "
                "AND key = 'anchor'"
            ),
            {"personality": "[1, 2, 3]", "public_id": created["public_id"]},
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}")

    body = response.json()
    assert response.status_code == 500
    # Not the anonymous fallback: the archive fault is named in the contract.
    assert body["code"] == 50003
    assert body["code"] != 500
    assert body["message"] != "internal server error"
    assert "corrupted" in body["message"]


@pytest.mark.parametrize(
    ("corrupt_sql", "corrupt_value"),
    [
        (
            "UPDATE endings SET conditions = :value WHERE story_id = "
            "(SELECT id FROM stories WHERE public_id = :public_id)",
            '"oops"',
        ),
        (
            "UPDATE choices SET effects = :value WHERE episode_id IN "
            "(SELECT id FROM episodes WHERE story_id = "
            "(SELECT id FROM stories WHERE public_id = :public_id))",
            '[{"delta": 12}]',
        ),
    ],
    ids=["endings_conditions_string", "choices_effects_missing_metric_key"],
)
def test_get_story_with_unpackable_json_columns_returns_500_50003(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    corrupt_sql: str,
    corrupt_value: str,
) -> None:
    """Shapes pydantic alone does not catch must still surface as 50003.

    Both cases load as valid JSON and only fail while the rebuild code unpacks
    fields: indexing a string raises TypeError, a missing mapping key raises
    KeyError. Neither may escape as a bare 500 or an exception from the route.
    """
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        session.execute(
            text(corrupt_sql),
            {"value": corrupt_value, "public_id": created["public_id"]},
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}")

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == 50003
    assert body["code"] != 500
    assert body["message"] != "internal server error"
    assert "corrupted" in body["message"]


def test_get_story_with_scalar_json_personality_returns_500_50003(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    """``list("abc")`` would silently rewrite the column instead of failing.

    The column holds a JSON string rather than an array, so ``list()`` would
    hand pydantic ``["a", "b", "c"]`` and the detail endpoint would answer 200
    with mangled data. It must surface as the named archive-corruption fault.
    """
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        session.execute(
            text(
                "UPDATE characters SET personality = :personality "
                "WHERE story_id = "
                "(SELECT id FROM stories WHERE public_id = :public_id) "
                "AND key = 'anchor'"
            ),
            {"personality": '"abc"', "public_id": created["public_id"]},
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}")

    body = response.json()
    assert response.status_code != 200
    assert response.status_code == 500
    assert body["code"] == 50003
    assert "corrupted" in body["message"]


def test_get_story_with_corrupt_invalid_json_personality_returns_500_50003(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    """SQLite does not enforce JSON validity, so bare text must still be 50003.

    ``UPDATE characters SET personality = 'abc'`` stores invalid JSON, and
    SQLAlchemy raises ``json.JSONDecodeError`` while ``load_blueprint`` is
    still materialising rows, before ``_require_string_list`` can inspect the
    value. That path must inherit the same archive-corruption contract instead
    of escaping as an anonymous 500.
    """
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    with session_factory() as session:
        session.execute(
            text(
                "UPDATE characters SET personality = :personality "
                "WHERE story_id = "
                "(SELECT id FROM stories WHERE public_id = :public_id) "
                "AND key = 'anchor'"
            ),
            {"personality": "abc", "public_id": created["public_id"]},
        )
        session.commit()

    response = api_client.get(f"/api/stories/{created['public_id']}")

    body = response.json()
    assert response.status_code != 200
    assert response.status_code == 500
    assert body["code"] == 50003
    assert body["code"] != 500
    assert body["message"] != "internal server error"
    assert "corrupted" in body["message"]


def test_get_story_openapi_declares_archive_corruption_500(
    api_client: TestClient,
) -> None:
    schema = api_client.get("/openapi.json").json()
    responses = schema["paths"]["/api/stories/{public_id}"]["get"]["responses"]

    assert "500" in responses
    assert "50003" in responses["500"]["description"]


def test_save_blueprint_inside_outer_transaction_rolls_back_with_it(
    session_factory: sessionmaker[Session],
) -> None:
    """The savepoint branch must not commit behind the caller's back.

    ``save_blueprint`` takes ``begin_nested()`` whenever the session already
    has a transaction. Releasing that savepoint makes the rows visible inside
    the outer transaction, but only the caller's commit may make them survive.
    """
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        session.begin()
        save_blueprint(session, blueprint)
        assert _row_count(session, Story) == 1, "外层事务内应能看到刚写入的故事"
        session.rollback()

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


def test_save_blueprint_inside_outer_transaction_survives_outer_commit(
    session_factory: sessionmaker[Session],
) -> None:
    """Releasing the savepoint hands the whole tree to the caller's commit."""
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        session.begin()
        public_id = save_blueprint(session, blueprint).public_id
        session.commit()

    with session_factory() as session:
        restored = load_blueprint(session, public_id)
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

    assert restored is not None
    assert restored.model_dump() == blueprint.model_dump()
    assert counts == {
        "stories": 1,
        "characters": 2,
        "metrics": 2,
        "episodes": 3,
        "choices": 6,
        "endings": 3,
        "story_state_changes": 1,
    }


def test_savepoint_failure_leaves_outer_transaction_usable_and_no_residue(
    session_factory: sessionmaker[Session],
) -> None:
    """A failed savepoint must roll back only its own tree, not poison the session."""
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data())

    with session_factory() as session:
        session.begin()

        def fail_after_flush(db_session, flush_context) -> None:
            raise RuntimeError("forced savepoint failure")

        event.listen(session, "after_flush_postexec", fail_after_flush, once=True)
        with pytest.raises(RuntimeError, match="forced savepoint failure"):
            save_blueprint(session, blueprint)

        assert _row_count(session, Story) == 0, "失败的 savepoint 必须整棵树回滚"

        survivor_id = save_blueprint(session, blueprint).public_id
        session.commit()

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
        stored_ids = list(session.scalars(select(Story.public_id)))

    assert stored_ids == [survivor_id], "失败的树不能留下任何 Story 行"
    assert counts == {
        "stories": 1,
        "characters": 2,
        "metrics": 2,
        "episodes": 3,
        "choices": 6,
        "endings": 3,
        "story_state_changes": 1,
    }


def test_story_list_timestamps_are_utc_with_explicit_offset(
    api_client: TestClient,
) -> None:
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    response = api_client.get("/api/stories")

    assert response.status_code == 200
    item = next(
        candidate
        for candidate in response.json()["data"]["items"]
        if candidate["public_id"] == created["public_id"]
    )
    for field in ("created_at", "updated_at"):
        # UTC may be written as ``Z`` or ``+00:00``; both are unambiguous
        # ISO-8601. What matters is that an offset is present at all, because
        # a bare naive string is what made clients guess their own timezone.
        assert item[field].endswith(("Z", "+00:00")), item[field]
        assert datetime.fromisoformat(item[field]).utcoffset() == timedelta(0)


def test_story_state_change_occurred_at_is_utc_with_explicit_offset(
    api_client: TestClient,
) -> None:
    created = api_client.post(
        "/api/stories",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    ).json()["data"]

    response = api_client.get(f"/api/stories/{created['public_id']}/state")

    assert response.status_code == 200
    occurred_at = response.json()["data"]["recent_state_changes"][0]["occurred_at"]
    assert occurred_at.endswith(("Z", "+00:00")), occurred_at
    assert datetime.fromisoformat(occurred_at).utcoffset() == timedelta(0)


def test_as_utc_normalizes_naive_aware_and_none() -> None:
    naive = datetime(2026, 11, 20, 1, 12, 33, 123456)
    aware = datetime(
        2026,
        11,
        20,
        9,
        12,
        33,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert as_utc(naive) == naive.replace(tzinfo=timezone.utc)
    assert as_utc(aware) == naive.replace(tzinfo=timezone.utc)
    assert as_utc(None) is None
