"""HTTP and service contract for cached narration.

The engine tests pin the arithmetic; these pin the batch's core promise: one
player event is narrated once. A replay must answer from the stored row without
calling the provider, a failed validation must write nothing, and every failure
has a stable code.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.dependencies import get_db_session
from app.main import create_app
from app.models import (
    Base,
    Narration,
    StateChangeEventType,
    Story,
    StoryStateChange,
)
from app.prompts.narration import build_messages
from app.schemas.story_blueprint import StoryBlueprint
from app.services import narrator
from app.services.narrator import load_context, validate_narration
from app.services.play_engine import advance_story
from app.services.story_store import save_blueprint
from app.api.narrations import get_narration_client
from tests.blueprint_factory import valid_blueprint_data


# 174 Hanzi, no Markdown, no JSON, no digits. Used as the "good" reply.
VALID_NARRATION = (
    "你把耳机往下一拉，把那段录音推到所有人面前。直播间里先是死一样的安静，"
    "紧接着弹幕像潮水一样涌上来。阿川愣在原地，手指悬在键盘上迟迟没有落下，"
    "屏幕的冷光把他的脸色照得发白。老K在连线那头冷笑了一声，却没有立刻接话。"
    "你听见自己的心跳压过了背景音乐，也听见有人在门外停下脚步。那一刻你明白，"
    "接下来每一句话都会被人反复放大，而你已经没有退路，只能把腰背挺直，"
    "迎着镜头把真相一个字一个字说完。"
)


class FakeNarrationClient:
    def __init__(self, outputs: list[str | Exception] | None = None) -> None:
        self.outputs = list(outputs) if outputs is not None else [VALID_NARRATION]
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> LlmReply:
        self.calls.append(messages)
        if not self.outputs:
            raise AssertionError("fake narration client has no queued output")
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return LlmReply(output, "deepseek-chat", 11, 22)


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
def fake_client() -> FakeNarrationClient:
    return FakeNarrationClient()


@pytest.fixture
def api_client(
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_narration_client] = lambda: fake_client
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _create_story(
    factory: sessionmaker[Session], data: dict | None = None
) -> str:
    blueprint = StoryBlueprint.model_validate(data or valid_blueprint_data())
    with factory() as session:
        return save_blueprint(session, blueprint).public_id


def _advance(
    factory: sessionmaker[Session],
    public_id: str,
    choice: str = "e1_truth",
) -> int:
    with factory() as session:
        return advance_story(session, public_id, choice).sequence


def _choice_sequences(
    factory: sessionmaker[Session], public_id: str
) -> list[int]:
    """The narration anchor of every turn, in play order."""
    with factory() as session:
        return list(
            session.scalars(
                select(StoryStateChange.sequence)
                .join(Story, Story.id == StoryStateChange.story_id)
                .where(
                    Story.public_id == public_id,
                    StoryStateChange.event_type
                    == StateChangeEventType.CHOICE_SELECTED.value,
                )
                .order_by(StoryStateChange.sequence)
            )
        )


def _narration_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(Narration)) or 0


def _url(public_id: str, sequence: int) -> str:
    return f"/api/stories/{public_id}/narrations/{sequence}"


def test_first_read_generates_and_persists_one_narration(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    public_id = _create_story(session_factory)
    outcome_sequence = _advance(session_factory, public_id)
    turn_sequence = _choice_sequences(session_factory, public_id)[0]

    response = api_client.get(_url(public_id, outcome_sequence))

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["public_id"] == public_id
    # The turn's narration is addressed by its anchor, not by the row asked for.
    assert body["data"]["sequence"] == turn_sequence
    assert body["data"]["text"] == VALID_NARRATION
    assert body["data"]["model"] == "deepseek-chat"
    assert len(fake_client.calls) == 1
    assert _narration_count(session_factory) == 1


def test_replay_returns_the_same_text_without_calling_the_model_again(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    public_id = _create_story(session_factory)
    sequence = _advance(session_factory, public_id)

    first = api_client.get(_url(public_id, sequence))
    second = api_client.get(_url(public_id, sequence))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["text"] == second.json()["data"]["text"]
    assert len(fake_client.calls) == 1, "缓存命中不能再调用模型"
    assert _narration_count(session_factory) == 1


def test_one_turn_is_narrated_once_for_any_of_its_rows(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    """P0 guard: one play action writes several player rows, one narration.

    Before the cache key became the turn anchor, each row generated its own
    text — five requests meant five rows and five model calls.
    """
    public_id = _create_story(session_factory)
    outcome_sequence = _advance(session_factory, public_id)
    turn_sequence = _choice_sequences(session_factory, public_id)[0]
    assert turn_sequence < outcome_sequence, "the turn must write several rows"
    # Extra outputs would only be consumed by the regression this test guards.
    fake_client.outputs = [VALID_NARRATION] * 6

    first = api_client.get(_url(public_id, turn_sequence))
    second = api_client.get(_url(public_id, outcome_sequence))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["text"] == second.json()["data"]["text"]
    assert (
        first.json()["data"]["sequence"]
        == second.json()["data"]["sequence"]
        == turn_sequence
    )

    for sequence in range(2, outcome_sequence + 1):
        response = api_client.get(_url(public_id, sequence))
        assert response.status_code == 200, response.text
        assert response.json()["data"]["sequence"] == turn_sequence

    assert len(fake_client.calls) == 1, "一个回合只允许调用一次模型"
    assert _narration_count(session_factory) == 1


def test_second_turn_prompt_does_not_leak_the_first_turn(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    fake_client.outputs = [VALID_NARRATION, VALID_NARRATION]
    data = valid_blueprint_data()
    data["episodes"][0]["choices"][0]["text"] = "第一回合独有的选项文本"
    data["episodes"][1]["choices"][1]["text"] = "第二回合独有的选项文本"
    public_id = _create_story(session_factory, data)

    _advance(session_factory, public_id, "e1_truth")
    _advance(session_factory, public_id, "e2_traffic")
    first_turn, second_turn = _choice_sequences(session_factory, public_id)

    second = api_client.get(_url(public_id, second_turn))

    assert second.status_code == 200
    second_prompt = "\n".join(
        message["content"] for message in fake_client.calls[0]
    )
    assert "第二回合独有的选项文本" in second_prompt
    assert "第一回合独有的选项文本" not in second_prompt

    # Ask for the first turn only after turn two is archived: the next
    # choice's upper bound must keep turn two's metric changes out of it.
    first = api_client.get(_url(public_id, first_turn))

    assert first.status_code == 200
    first_prompt = "\n".join(
        message["content"] for message in fake_client.calls[1]
    )
    assert "第一回合独有的选项文本" in first_prompt
    assert "下降" not in first_prompt, "第一回合的旁白不能混入第二回合的变化"

    assert len(fake_client.calls) == 2
    assert _narration_count(session_factory) == 2


def test_fenced_reply_is_repaired_on_the_second_attempt(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    fake_client.outputs = [
        "```\n" + VALID_NARRATION + "\n```",
        VALID_NARRATION,
    ]
    public_id = _create_story(session_factory)
    sequence = _advance(session_factory, public_id)

    response = api_client.get(_url(public_id, sequence))

    assert response.status_code == 200
    assert response.json()["data"]["text"] == VALID_NARRATION
    assert len(fake_client.calls) == 2
    repair_message = fake_client.calls[1][-1]["content"]
    assert "没有通过校验" in repair_message
    assert "代码围栏" in repair_message
    assert _narration_count(session_factory) == 1


def test_three_rejected_replies_return_422_and_write_nothing(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    bad_reply = json.dumps({"narration": VALID_NARRATION}, ensure_ascii=False)
    fake_client.outputs = [bad_reply, bad_reply, bad_reply]
    public_id = _create_story(session_factory)
    sequence = _advance(session_factory, public_id)

    response = api_client.get(_url(public_id, sequence))

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == 42202
    assert body["data"] is None
    assert len(fake_client.calls) == 3
    assert "JSON" in fake_client.calls[1][-1]["content"]
    assert _narration_count(session_factory) == 0, "三次被拒的生成不能落库"


def test_unknown_story_returns_404_with_40401(
    api_client: TestClient,
    fake_client: FakeNarrationClient,
) -> None:
    response = api_client.get(_url("does-not-exist", 1))

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == 40401
    assert body["message"] == "story not found"
    assert fake_client.calls == []


@pytest.mark.parametrize("sequence", [1, 999])
def test_missing_or_generated_sequence_returns_404_with_40402(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
    sequence: int,
) -> None:
    """1 is the generated ``story_created`` row; 999 is out of range."""
    public_id = _create_story(session_factory)
    _advance(session_factory, public_id)

    response = api_client.get(_url(public_id, sequence))

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == 40402
    assert body["data"] is None
    assert fake_client.calls == []


def test_player_event_before_the_choice_narrates_the_same_turn(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    """Sequence 2 is the first turn's ``story_status_changed``.

    It is a player event written before ``choice_selected`` (sequence 3), so it
    must still resolve to the turn rather than answer 40402.
    """
    public_id = _create_story(session_factory)
    _advance(session_factory, public_id)

    response = api_client.get(_url(public_id, 2))

    assert response.status_code == 200
    assert response.json()["data"]["text"] == VALID_NARRATION
    assert len(fake_client.calls) == 1


def test_unsupported_blueprint_version_returns_409_with_40902(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    public_id = _create_story(session_factory)
    sequence = _advance(session_factory, public_id)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE stories SET blueprint_version = 0 "
                "WHERE public_id = :public_id"
            ),
            {"public_id": public_id},
        )
        session.commit()

    response = api_client.get(_url(public_id, sequence))

    body = response.json()
    assert response.status_code == 409
    assert body["code"] == 40902
    assert "blueprint version 0" in body["message"]
    assert "supports version 1" in body["message"]
    assert fake_client.calls == []
    assert _narration_count(session_factory) == 0


@pytest.mark.parametrize(
    ("text", "expected_issue"),
    [
        ("```\n" + VALID_NARRATION + "\n```", "代码围栏"),
        (json.dumps({"narration": VALID_NARRATION}, ensure_ascii=False), "JSON"),
        ("你" * 10, "过短"),
        ("你" * 401, "过长"),
        (VALID_NARRATION, None),
    ],
)
def test_validate_narration_rules(
    text: str, expected_issue: str | None
) -> None:
    issues = validate_narration(text)

    if expected_issue is None:
        assert issues == []
    else:
        assert any(expected_issue in issue for issue in issues)


def test_prompt_never_contains_character_secrets_or_metric_values(
    session_factory: sessionmaker[Session],
) -> None:
    data = valid_blueprint_data()
    public_id = _create_story(session_factory, data)
    sequence = _advance(session_factory, public_id)

    with session_factory() as session:
        context = load_context(session, public_id, sequence)
    assert context is not None
    rendered = "\n".join(message["content"] for message in build_messages(context))

    for character in data["characters"]:
        assert character["secret"] not in rendered, "secret 绝不能进入旁白 prompt"
    assert "阿川" in rendered
    assert "新人主播" in rendered
    # e1_truth leaves reputation=62 and mindset=50; neither may be read out.
    assert "62" not in rendered
    assert "50" not in rendered
    assert "reputation" not in rendered
    assert "明显上升" in rendered


def test_provider_failure_uses_the_existing_provider_error_mapping(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
    fake_client: FakeNarrationClient,
) -> None:
    fake_client.outputs = [
        DeepSeekClientError(
            "bad credentials", retryable=False, status_code=401
        )
    ]
    public_id = _create_story(session_factory)
    sequence = _advance(session_factory, public_id)

    response = api_client.get(_url(public_id, sequence))

    body = response.json()
    assert response.status_code == 503
    assert body["code"] == 50302
    assert _narration_count(session_factory) == 0


def test_insert_race_returns_the_winner_instead_of_a_500(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    """Two first reads can both miss the cache; the loser must read back."""
    public_id = _create_story(session_factory)
    outcome_sequence = _advance(session_factory, public_id)
    turn_sequence = _choice_sequences(session_factory, public_id)[0]
    with session_factory() as session:
        story_id = session.scalar(
            select(Story.id).where(Story.public_id == public_id)
        )
        session.add(
            Narration(
                story_id=story_id,
                # The winner is stored under the turn anchor, which is why the
                # request for ``outcome_sequence`` must still find it.
                sequence=turn_sequence,
                text="winner text",
                model="other-model",
            )
        )
        session.commit()

    real_find = narrator._find_cached
    lookups = {"count": 0}

    def miss_once(session, story_id, requested_sequence):
        lookups["count"] += 1
        if lookups["count"] == 1:
            return None
        return real_find(session, story_id, requested_sequence)

    monkeypatch.setattr(narrator, "_find_cached", miss_once)
    client = FakeNarrationClient([VALID_NARRATION])

    with session_factory() as session:
        result = asyncio.run(
            narrator.generate(session, public_id, outcome_sequence, client=client)
        )

    assert result.text == "winner text"
    assert len(client.calls) == 1
    assert lookups["count"] == 2
    assert _narration_count(session_factory) == 1
