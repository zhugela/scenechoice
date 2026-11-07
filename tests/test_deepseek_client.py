import asyncio
import json

import httpx
import pytest

from app.clients.deepseek import DeepSeekClient, DeepSeekClientError
from app.services.story_planner import StoryPlanner
from tests.blueprint_factory import valid_blueprint_data


def make_client(handler) -> DeepSeekClient:
    return DeepSeekClient(
        api_key="secret",
        base_url="https://api.deepseek.test",
        model="deepseek-chat",
        timeout=1,
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_client_parses_content_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        assert body == {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 9},
            },
        )

    reply = asyncio.run(make_client(handler).complete([{"role": "user", "content": "hi"}]))
    assert reply.content == "{}"
    assert (reply.prompt_tokens, reply.completion_tokens) == (7, 9)
    assert make_client(handler).timeout == 1


def test_deepseek_client_does_not_retry_authentication_error() -> None:
    client = make_client(lambda request: httpx.Response(401, text="key leaked"))
    with pytest.raises(DeepSeekClientError, match="DeepSeek request failed") as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is False
    assert error.value.status_code == 401
    assert "key leaked" not in str(error.value)


def test_deepseek_client_marks_rate_limit_as_retryable() -> None:
    client = make_client(
        lambda request: httpx.Response(429, text="slow down", headers={"Retry-After": "2"})
    )
    with pytest.raises(DeepSeekClientError) as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is True
    assert error.value.status_code == 429
    assert error.value.retry_after_seconds == 2


def test_deepseek_client_marks_invalid_provider_payload_as_retryable() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(DeepSeekClientError) as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is True


def test_deepseek_client_marks_non_object_payload_as_retryable() -> None:
    client = make_client(lambda request: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(DeepSeekClientError, match="invalid response") as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is True


def test_deepseek_client_marks_null_content_as_retryable() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": None}}]},
        )
    )
    with pytest.raises(DeepSeekClientError, match="invalid response") as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is True


def test_deepseek_client_marks_timeout_as_retryable() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(timeout_handler)
    with pytest.raises(DeepSeekClientError, match="DeepSeek request failed") as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))

    assert error.value.retryable is True
    assert error.value.status_code is None


@pytest.mark.parametrize("status_code", [408, 500, 503])
def test_deepseek_client_marks_transient_http_statuses_as_retryable(status_code: int) -> None:
    client = make_client(lambda request: httpx.Response(status_code, text="temporary"))
    with pytest.raises(DeepSeekClientError) as error:
        asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert error.value.retryable is True
    assert error.value.status_code == status_code


def test_deepseek_client_and_story_planner_integrate_through_provider_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(valid_blueprint_data(), ensure_ascii=False)
                        }
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22},
            },
        )

    result = asyncio.run(StoryPlanner(make_client(handler)).plan("主播遭遇直播事故", 3))
    assert result.blueprint.title == "麦克风没有关"
    assert result.model == "deepseek-chat"
    assert (result.prompt_tokens, result.completion_tokens) == (11, 22)
