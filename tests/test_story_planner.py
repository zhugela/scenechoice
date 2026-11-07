import asyncio
import json
import logging

import pytest

from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.services.story_planner import StoryPlanner, StoryPlanningError
from tests.blueprint_factory import valid_blueprint_data


class FakeClient:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = iter(outputs)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> LlmReply:
        self.calls.append(messages)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return LlmReply(output, "deepseek-chat", 10, 20)


def test_planner_returns_valid_first_attempt() -> None:
    client = FakeClient([json.dumps(valid_blueprint_data(), ensure_ascii=False)])
    result = asyncio.run(StoryPlanner(client).plan("主播遭遇直播事故", 3))
    assert result.attempts == 1
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 20


def test_success_log_contains_metrics_but_not_user_content(caplog) -> None:
    inspiration = "PRIVATE-STORY-INSPIRATION"
    client = FakeClient([json.dumps(valid_blueprint_data(), ensure_ascii=False)])

    with caplog.at_level(logging.INFO, logger="app.services.story_planner"):
        asyncio.run(StoryPlanner(client).plan(inspiration, 3))

    assert "model=deepseek-chat" in caplog.text
    assert "attempts=1" in caplog.text
    assert "prompt_tokens=10" in caplog.text
    assert "completion_tokens=20" in caplog.text
    assert "duration_ms=" in caplog.text
    assert inspiration not in caplog.text


def test_failure_log_is_sanitized(caplog) -> None:
    secret = "PRIVATE-API-KEY"
    client = FakeClient([DeepSeekClientError("DeepSeek request failed", retryable=False, status_code=401)])

    with caplog.at_level(logging.WARNING, logger="app.services.story_planner"):
        with pytest.raises(DeepSeekClientError):
            asyncio.run(StoryPlanner(client).plan(secret, 3))

    assert "status_code=401" in caplog.text
    assert "retryable=False" in caplog.text
    assert secret not in caplog.text


def test_planner_repairs_invalid_json() -> None:
    client = FakeClient(["not json", json.dumps(valid_blueprint_data(), ensure_ascii=False)])
    result = asyncio.run(StoryPlanner(client).plan("主播遭遇直播事故", 3))
    assert result.attempts == 2
    assert len(client.calls) == 2
    assert "未通过校验" in client.calls[1][-1]["content"]


def test_planner_fails_after_three_attempts() -> None:
    client = FakeClient(["bad", "bad", "bad"])
    with pytest.raises(StoryPlanningError) as error:
        asyncio.run(StoryPlanner(client).plan("主播遭遇直播事故", 3))
    assert error.value.attempts == 3
    assert error.value.issues
    assert any("Invalid JSON" in issue for issue in error.value.issues)


def test_planner_rejects_wrong_requested_episode_count() -> None:
    client = FakeClient([json.dumps(valid_blueprint_data(3))] * 3)
    with pytest.raises(StoryPlanningError):
        asyncio.run(StoryPlanner(client).plan("主播遭遇直播事故", 5))


def test_planner_retries_transient_model_error() -> None:
    client = FakeClient([
        DeepSeekClientError("temporary", retryable=True),
        json.dumps(valid_blueprint_data(), ensure_ascii=False),
    ])
    result = asyncio.run(StoryPlanner(client, retry_base_seconds=0).plan("主播遭遇直播事故", 3))
    assert result.attempts == 2


def test_planner_exposes_sanitized_model_error_after_three_attempts() -> None:
    client = FakeClient([DeepSeekClientError("safe", retryable=True)] * 3)
    with pytest.raises(DeepSeekClientError, match="safe"):
        asyncio.run(StoryPlanner(client, retry_base_seconds=0).plan("主播遭遇直播事故", 3))


def test_planner_does_not_retry_permanent_model_error() -> None:
    client = FakeClient([
        DeepSeekClientError("bad credentials", retryable=False, status_code=401),
        json.dumps(valid_blueprint_data(), ensure_ascii=False),
    ])
    with pytest.raises(DeepSeekClientError, match="bad credentials"):
        asyncio.run(StoryPlanner(client).plan("主播遭遇直播事故", 3))
    assert len(client.calls) == 1


def test_planner_uses_exponential_backoff_and_honors_retry_after() -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    client = FakeClient([
        DeepSeekClientError("rate limited", retryable=True, status_code=429, retry_after_seconds=3),
        DeepSeekClientError("network", retryable=True),
        json.dumps(valid_blueprint_data(), ensure_ascii=False),
    ])
    planner = StoryPlanner(
        client,
        retry_base_seconds=0.5,
        retry_max_seconds=2,
        sleep=fake_sleep,
    )

    result = asyncio.run(planner.plan("主播遭遇直播事故", 3))

    assert result.attempts == 3
    assert delays == [2, 1.0]
