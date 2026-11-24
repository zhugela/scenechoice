"""Behavior of the ``Idempotency-Key`` contract on ``POST /api/stories``.

The fixtures mirror ``tests/test_stories_api.py`` so this module can exercise
the route without changing that file's expectations. Migration assertions for
the new table live here, matching the batch plan.
"""

import json
import os
import subprocess
import sys
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.deepseek import LlmReply
from app.dependencies import get_db_session, get_story_planner
from app.main import create_app
from app.models import Base, IdempotencyRecord, Story
from app.models.base import as_utc, utcnow
from app.services.idempotency import (
    STORIES_CREATE_SCOPE,
    request_fingerprint,
)
from app.services.story_planner import StoryPlanner, StoryPlanningError
from app.services.story_store import BlueprintStorageError
from tests.blueprint_factory import valid_blueprint_data

INSPIRATION = "一个小主播误开麦后被恶意剪辑"
REQUEST_BODY = {"inspiration": INSPIRATION, "episode_count": 3}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    async def complete(self, messages: list[dict[str, str]]) -> LlmReply:
        return LlmReply(
            json.dumps(valid_blueprint_data(), ensure_ascii=False),
            "fake-model",
            4,
            8,
        )


class SwitchablePlanner:
    """A planner whose failure mode can be flipped between requests."""

    def __init__(self) -> None:
        self.error: Exception | None = None
        self._planner = StoryPlanner(FakeClient())

    async def plan(self, inspiration: str, episode_count: int):
        if self.error is not None:
            raise self.error
        return await self._planner.plan(inspiration, episode_count)


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


def _make_client(factory: sessionmaker[Session], planner: object) -> TestClient:
    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_story_planner] = lambda: planner
    return TestClient(app)


@pytest.fixture
def api_client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    with _make_client(session_factory, StoryPlanner(FakeClient())) as client:
        yield client


def _post(client: TestClient, *, key: str | None = None, body: dict | None = None):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post("/api/stories", json=body or REQUEST_BODY, headers=headers)


def _story_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Story)) or 0


def _record_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(IdempotencyRecord)) or 0


def test_same_key_twice_replays_the_first_response_and_stores_one_story(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first = _post(api_client, key="retry-key-1")
    second = _post(api_client, key="retry-key-1")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert "Idempotent-Replay" not in first.headers
    assert second.json() == first.json()

    with session_factory() as session:
        assert _story_count(session) == 1
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.state == "completed"
        assert record.status_code == 201
        assert record.scope == STORIES_CREATE_SCOPE
        assert record.key == "retry-key-1"
        assert record.response_body == first.json()


def test_same_key_with_a_different_body_returns_409_40903_without_a_second_story(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first = _post(api_client, key="retry-key-2")
    second = _post(
        api_client,
        key="retry-key-2",
        body={"inspiration": "完全不同的另一个故事灵感", "episode_count": 3},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == 40903
    assert second.json()["data"] is None

    with session_factory() as session:
        assert _story_count(session) == 1
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.fingerprint == request_fingerprint(REQUEST_BODY)
        assert record.state == "completed"


def test_pending_key_younger_than_ten_minutes_returns_409_40904(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    now = utcnow()
    with session_factory() as session:
        session.add(
            IdempotencyRecord(
                scope=STORIES_CREATE_SCOPE,
                key="busy-key",
                fingerprint=request_fingerprint(REQUEST_BODY),
                state="pending",
                status_code=None,
                response_body=None,
                created_at=now - timedelta(minutes=1),
                updated_at=now - timedelta(minutes=1),
            )
        )
        session.commit()

    response = _post(api_client, key="busy-key")

    assert response.status_code == 409
    assert response.json()["code"] == 40904
    with session_factory() as session:
        assert _story_count(session) == 0
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.state == "pending"


def test_pending_key_older_than_ten_minutes_is_reset_and_generates(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    old = utcnow() - timedelta(minutes=20)
    with session_factory() as session:
        session.add(
            IdempotencyRecord(
                scope=STORIES_CREATE_SCOPE,
                key="crashed-key",
                fingerprint=request_fingerprint(REQUEST_BODY),
                state="pending",
                status_code=None,
                response_body=None,
                created_at=old,
                updated_at=old,
            )
        )
        session.commit()

    response = _post(api_client, key="crashed-key")

    assert response.status_code == 201
    with session_factory() as session:
        assert _story_count(session) == 1
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.state == "completed"
        assert record.status_code == 201
        assert record.fingerprint == request_fingerprint(REQUEST_BODY)
        assert as_utc(record.updated_at) > old


def test_requests_without_a_key_keep_generating_one_story_each(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first = _post(api_client)
    second = _post(api_client)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["public_id"] != second.json()["data"]["public_id"]
    assert "Idempotent-Replay" not in second.headers

    with session_factory() as session:
        assert _story_count(session) == 2
        assert _record_count(session) == 0


def test_generation_failure_releases_the_claim_so_the_same_key_can_retry(
    session_factory: sessionmaker[Session],
) -> None:
    planner = SwitchablePlanner()
    planner.error = StoryPlanningError("invalid blueprint", attempts=3)

    with _make_client(session_factory, planner) as client:
        failed = _post(client, key="retry-after-failure")

        assert failed.status_code == 422
        assert failed.json()["code"] == 42201
        with session_factory() as session:
            assert _record_count(session) == 0
            assert _story_count(session) == 0

        planner.error = None
        retried = _post(client, key="retry-after-failure")

    assert retried.status_code == 201
    with session_factory() as session:
        assert _story_count(session) == 1
        record = session.scalar(select(IdempotencyRecord))
        assert record is not None
        assert record.state == "completed"


def test_storage_failure_releases_the_claim_so_the_same_key_can_retry(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_store(session: Session, blueprint: object) -> None:
        raise BlueprintStorageError(["forced storage failure"])

    monkeypatch.setattr("app.api.stories.save_blueprint", fail_to_store)

    with _make_client(session_factory, StoryPlanner(FakeClient())) as client:
        failed = _post(client, key="retry-after-storage-failure")

    assert failed.status_code == 422
    assert failed.json()["code"] == 42201
    with session_factory() as session:
        assert _record_count(session) == 0
        assert _story_count(session) == 0

    monkeypatch.undo()
    with _make_client(session_factory, StoryPlanner(FakeClient())) as client:
        retried = _post(client, key="retry-after-storage-failure")

    assert retried.status_code == 201
    with session_factory() as session:
        assert _story_count(session) == 1


def test_overlong_idempotency_key_returns_422(
    api_client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = _post(api_client, key="x" * 121)

    assert response.status_code == 422
    with session_factory() as session:
        assert _record_count(session) == 0
        assert _story_count(session) == 0


def test_concurrent_insert_losing_the_unique_race_is_judged_after_re_read(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the window where a second request read "no record" first.

    The winner's committed row makes the second INSERT raise ``IntegrityError``.
    ``claim`` must roll back that insert, re-read the winner, and answer
    ``in_progress`` instead of leaking a 500 (or creating a second story).
    """
    from app.services import idempotency as idempotency_service

    now = utcnow()
    fingerprint = request_fingerprint(REQUEST_BODY)
    with session_factory() as session:
        session.add(
            IdempotencyRecord(
                scope=STORIES_CREATE_SCOPE,
                key="raced-key",
                fingerprint=fingerprint,
                state="pending",
                status_code=None,
                response_body=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    real_find = idempotency_service._find
    calls = {"count": 0}

    def find_missing_on_first_look(session, *, scope, key):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return real_find(session, scope=scope, key=key)

    monkeypatch.setattr(idempotency_service, "_find", find_missing_on_first_look)

    with session_factory() as session:
        claim = idempotency_service.claim(
            session,
            scope=STORIES_CREATE_SCOPE,
            key="raced-key",
            fingerprint=fingerprint,
            now=now,
        )

    assert claim.outcome == "in_progress"
    assert calls["count"] >= 2
    with session_factory() as session:
        assert _record_count(session) == 1
        assert _story_count(session) == 0


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["SCENECHOICE_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_migration_creates_idempotency_records_with_unique_scope_and_key(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "idempotency.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    # Pin the migration under test. Upgrading to "head" made this test assert
    # that 0003 was the latest revision, so any later migration (0004 adds
    # narrations) broke it without touching the idempotency DDL it checks.
    upgraded = _run_alembic(database_url, "upgrade", "20261122_0003")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            columns = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info(idempotency_records)")
                )
            }
        assert revision == "20261122_0003"
        assert columns == {
            "id",
            "scope",
            "key",
            "fingerprint",
            "state",
            "status_code",
            "response_body",
            "created_at",
            "updated_at",
        }

        insert_sql = text(
            """
            INSERT INTO idempotency_records (
                scope, key, fingerprint, state, status_code, response_body,
                created_at, updated_at
            ) VALUES (
                'stories.create', 'migration-key', 'fingerprint',
                'pending', NULL, NULL,
                '2026-11-22 00:00:00.000000', '2026-11-22 00:00:00.000000'
            )
            """
        )
        with engine.begin() as connection:
            connection.execute(insert_sql)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(insert_sql)
    finally:
        engine.dispose()
