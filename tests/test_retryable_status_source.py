import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.deepseek import DeepSeekClient, DeepSeekClientError, is_retryable_status
from app.dependencies import get_story_planner
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


def test_client_and_api_derive_transient_status_from_the_same_source() -> None:
    # The client (retry decision) and the API (temporary vs permanent mapping)
    # must agree on which HTTP status codes are transient, and both must read
    # that answer from `is_retryable_status`. Editing one layer's hardcoded set
    # without the other now makes this test fail.
    app = create_app()
    client = TestClient(app)

    for status in range(400, 600):
        # 1) Client: retryable flag must equal the shared predicate.
        assert _client_retryable_for_status(status) is is_retryable_status(status)

        # 2) API: same predicate decides temporary (50201) vs permanent (400/50202).
        #    401/403/402 are business overrides handled before this split, not part
        #    of the transient set, so they are excluded here.
        if 400 <= status < 500 and status in {401, 402, 403}:
            continue

        app.dependency_overrides[get_story_planner] = (
            lambda s=status: _FailingPlanner(
                DeepSeekClientError("provider failed", retryable=False, status_code=s)
            )
        )
        response = client.post(
            "/api/story-plans/preview",
            json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
        )

        expected_code = 50201 if is_retryable_status(status) else 50202
        assert response.json()["code"] == expected_code, (
            f"status={status} mapped to {response.json()['code']}, expected {expected_code}"
        )
