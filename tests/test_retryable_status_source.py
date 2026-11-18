import asyncio
from collections.abc import Generator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.clients.deepseek import DeepSeekClient, DeepSeekClientError, is_retryable_status
from app.dependencies import get_db_session, get_story_planner
from app.main import create_app


def _client_retryable_for_status(status_code: int) -> bool:
    """What the client's retry decision returns for a given provider HTTP status."""
    client = DeepSeekClient(
        api_key="secret",
        base_url="https://api.deepseek.test",
        model="deepseek-chat",
        timeout=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, text="x")),
    )
    with pytest.raises(DeepSeekClientError) as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    return error.value.retryable


class _FailingPlanner:
    def __init__(self, error: DeepSeekClientError) -> None:
        self.error = error

    async def plan(self, inspiration: str, episode_count: int):
        raise self.error


def _failing_planner_factory(error: DeepSeekClientError):
    def planner() -> _FailingPlanner:
        return _FailingPlanner(error)

    return planner


def test_client_and_api_derive_transient_status_from_the_same_source() -> None:
    # The client (retry decision) and both story endpoints (temporary vs
    # permanent mapping) must agree on which HTTP status codes are transient,
    # and every layer must read that answer from `is_retryable_status`. The
    # preview/persist comparison below is the net that catches one mapping
    # being edited without the other.
    app = create_app()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)
    request_body = {"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3}

    try:
        for status in range(400, 600):
            # 1) Client: retryable flag must equal the shared predicate.
            assert _client_retryable_for_status(status) is is_retryable_status(status)

            # 2) Both story endpoints must expose an identical contract. 401/402/
            #    403 are business overrides handled before the transient split,
            #    but they must still agree across routes.
            error = DeepSeekClientError(
                "provider failed", retryable=False, status_code=status
            )
            app.dependency_overrides[get_story_planner] = _failing_planner_factory(error)
            preview = client.post("/api/story-plans/preview", json=request_body)
            story = client.post("/api/stories", json=request_body)

            preview_contract = (
                preview.status_code,
                preview.json()["code"],
                preview.json()["message"],
            )
            story_contract = (
                story.status_code,
                story.json()["code"],
                story.json()["message"],
            )
            assert story_contract == preview_contract, (
                f"status={status}: preview={preview_contract}, stories={story_contract}"
            )

            if status in {401, 402, 403}:
                continue

            # 3) API: same predicate decides temporary (50201) vs permanent
            #    (400/50202).
            expected_code = 50201 if is_retryable_status(status) else 50202
            assert preview.json()["code"] == expected_code, (
                f"status={status} mapped to {preview.json()['code']}, expected {expected_code}"
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
