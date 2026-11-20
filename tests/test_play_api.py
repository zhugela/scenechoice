"""HTTP contract for the play endpoint.

The engine tests pin the arithmetic; these pin the thing a client actually
calls: one POST advances the archive in a single transaction, every failure has
a stable code, and a rejected action writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.dependencies import get_db_session
from app.main import create_app
from app.models import Base, Ending, Story, StoryStateChange
from app.schemas.story_blueprint import StoryBlueprint
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


@pytest.fixture
def api_client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _create_story(factory: sessionmaker[Session], data: dict | None = None) -> str:
    blueprint = StoryBlueprint.model_validate(data or valid_blueprint_data())
    with factory() as session:
        return save_blueprint(session, blueprint).public_id


def _change_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(StoryStateChange)) or 0


def _state(client: TestClient, public_id: str) -> dict:
    response = client.get(f"/api/stories/{public_id}/state")
    assert response.status_code == 200
    return response.json()["data"]


def test_one_post_advances_the_story_and_is_visible_in_the_state_endpoint(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    public_id = _create_story(session_factory)

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e1_truth"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["public_id"] == public_id
    assert data["status"] == "in_progress"
    assert data["episode_number"] == 1
    assert data["next_episode_number"] == 2
    assert data["ending_key"] is None
    assert {metric["metric_id"]: metric["current_value"] for metric in data["metrics"]} == {
        "reputation": 62,
        "mindset": 50,
    }

    state = _state(api_client, public_id)
    assert state["status"] == "in_progress"
    assert state["last_sequence"] == data["sequence"], "响应里的 sequence 必须是这一轮最后一条事件"
    events = [change["event_type"] for change in state["recent_state_changes"]]
    assert "choice_selected" in events
    assert "metric_changed" in events
    episodes = {episode["number"]: episode["status"] for episode in state["episodes"]}
    assert episodes == {1: "completed", 2: "in_progress", 3: "planned"}


def test_three_posts_through_the_api_reach_the_high_ending(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    public_id = _create_story(session_factory)

    for choice in ("e1_truth", "e2_truth", "e3_truth"):
        response = api_client.post(
            f"/api/stories/{public_id}/play", json={"choice_key": choice}
        )
        assert response.status_code == 200

    final = response.json()["data"]
    assert final["status"] == "completed"
    assert final["ending_key"] == "comeback"
    assert final["next_episode_number"] is None
    assert final["episode_number"] == 3


def test_unknown_story_returns_404_with_40401(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/stories/does-not-exist/play", json={"choice_key": "e1_truth"}
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 40401
    assert body["message"] == "story not found"
    assert body["data"] is None


def test_finished_story_returns_409_with_40901(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    public_id = _create_story(session_factory)
    for choice in ("e1_truth", "e2_truth", "e3_truth"):
        api_client.post(f"/api/stories/{public_id}/play", json={"choice_key": choice})

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e3_truth"}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == 40901
    assert body["message"] == "story has already finished"


def test_choice_from_another_episode_returns_400_and_writes_nothing(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    public_id = _create_story(session_factory)
    api_client.post(f"/api/stories/{public_id}/play", json={"choice_key": "e1_truth"})
    before_count = _change_count(session_factory)
    before_sequence = _state(api_client, public_id)["last_sequence"]

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e1_truth"}
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 40001
    assert body["message"] == "choice does not belong to the episode being played"
    assert _change_count(session_factory) == before_count, "被拒绝的选择不能留下任何事件"
    assert _state(api_client, public_id)["last_sequence"] == before_sequence


def _metrics(state: dict) -> dict[str, int]:
    return {metric["metric_id"]: metric["current_value"] for metric in state["metrics"]}


def test_no_matching_ending_returns_500_and_rolls_every_thing_back(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    public_id = _create_story(session_factory)
    with session_factory() as session:
        # Same damage a manual DB edit would cause: the blueprint still claims
        # endings exist, but the rows are gone.
        session.execute(delete(Ending))
        session.commit()

    for choice in ("e1_truth", "e2_truth"):
        assert (
            api_client.post(
                f"/api/stories/{public_id}/play", json={"choice_key": choice}
            ).status_code
            == 200
        )

    # This is the only failure path that mutates metric/episode rows in memory
    # *before* raising, so snapshot everything the write would have touched.
    before_count = _change_count(session_factory)
    before_state = _state(api_client, public_id)

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e3_truth"}
    )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == 50001

    after_state = _state(api_client, public_id)
    assert after_state["status"] == "in_progress", "失败结局的事务必须整体回滚"
    assert after_state["last_sequence"] == before_state["last_sequence"], "回滚后不能留下新事件"
    assert _change_count(session_factory) == before_count, "回滚后事件日志行数必须不变"
    assert _metrics(after_state) == _metrics(before_state), "回滚后指标必须不变"
    after_episodes = {episode["number"]: episode["status"] for episode in after_state["episodes"]}
    assert after_episodes[3] == "in_progress", "被回滚的那一集不能变成 completed"
    assert after_episodes[2] == "completed"


@pytest.mark.parametrize(
    "payload",
    [
        {"choice_key": ""},
        {},
        {"choice_key": "e1_truth", "episode": 1},
        {"choice": "e1_truth"},
    ],
)
def test_malformed_payload_returns_422(api_client: TestClient, payload: dict) -> None:
    response = api_client.post("/api/stories/any-id/play", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["message"] == "request validation failed"


def test_openapi_documents_the_play_contract(api_client: TestClient) -> None:
    schema = api_client.get("/openapi.json").json()

    path = schema["paths"]["/api/stories/{public_id}/play"]["post"]
    assert set(path["responses"]) >= {"200", "400", "404", "409", "422", "500"}
    assert "40001" in path["responses"]["400"]["description"]
    assert "40401" in path["responses"]["404"]["description"]
    assert "40901" in path["responses"]["409"]["description"]
    assert "50001" in path["responses"]["500"]["description"]


def test_old_blueprint_version_returns_409_40902_and_writes_nothing(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """详情接口挡住的旧存档，推进接口必须用同一个 409/40902 挡住。"""
    public_id = _create_story(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE stories SET blueprint_version = 0 "
                "WHERE public_id = :public_id"
            ),
            {"public_id": public_id},
        )
        session.commit()

    with session_factory() as session:
        before_stories = session.scalar(select(func.count()).select_from(Story))
    before_changes = _change_count(session_factory)

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e1_truth"}
    )

    body = response.json()
    assert response.status_code == 409
    assert body["code"] == 40902
    assert "blueprint version 0" in body["message"]
    assert "supports version 1" in body["message"]

    with session_factory() as session:
        after_stories = session.scalar(select(func.count()).select_from(Story))
        status = session.scalar(
            select(Story.status).where(Story.public_id == public_id)
        )
    assert after_stories == before_stories, "被版本闸拒绝的推进不能新增故事行"
    assert _change_count(session_factory) == before_changes, "被版本闸拒绝的推进不能新增事件"
    assert status == "ready", "版本闸必须在任何写入之前拦住"


def test_broken_choice_effect_returns_500_50003_instead_of_the_fallback(
    api_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """存档内部不一致（选项引用不存在的指标）应报 50003，而不是含糊的 50002。"""
    public_id = _create_story(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE choices SET effects = :effects "
                "WHERE key = 'e1_truth' AND episode_id = ("
                "SELECT episodes.id FROM episodes "
                "JOIN stories ON stories.id = episodes.story_id "
                "WHERE stories.public_id = :public_id AND episodes.number = 1)"
            ),
            {
                "effects": json.dumps([{"metric_key": "ghost", "delta": 12}]),
                "public_id": public_id,
            },
        )
        session.commit()

    before_changes = _change_count(session_factory)

    response = api_client.post(
        f"/api/stories/{public_id}/play", json={"choice_key": "e1_truth"}
    )

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == 50003
    assert body["code"] != 50002
    assert "corrupted" in body["message"]

    assert _change_count(session_factory) == before_changes, "存档损坏导致的失败不能留下半截事件"
    with session_factory() as session:
        status = session.scalar(
            select(Story.status).where(Story.public_id == public_id)
        )
    assert status == "ready", "损坏导致的失败必须整体回滚"


def test_openapi_documents_version_and_corruption_codes(
    api_client: TestClient,
) -> None:
    """U2 改写了两条描述；没有这条断言，40902/50003 的文档口径会再次漂移。"""
    schema = api_client.get("/openapi.json").json()

    responses = schema["paths"]["/api/stories/{public_id}/play"]["post"]["responses"]
    assert "40902" in responses["409"]["description"]
    assert "50003" in responses["500"]["description"]
