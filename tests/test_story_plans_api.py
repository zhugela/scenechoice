import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.config import get_settings
from app.dependencies import get_story_planner
from app.main import create_app
from app.services.story_planner import StoryPlanner, StoryPlanningError
from tests.blueprint_factory import valid_blueprint_data


class FakeClient:
    async def complete(self, messages: list[dict[str, str]]) -> LlmReply:
        return LlmReply(json.dumps(valid_blueprint_data(), ensure_ascii=False), "fake-model", 4, 8)


class FailingPlanner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def plan(self, inspiration: str, episode_count: int):
        raise self.error


def test_preview_story_plan_returns_blueprint_and_meta() -> None:
    app = create_app()
    app.dependency_overrides[get_story_planner] = lambda: StoryPlanner(FakeClient())
    response = TestClient(app).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["blueprint"]["episode_count"] == 3
    assert body["data"]["meta"] == {
        "attempts": 1,
        "model": "fake-model",
        "prompt_tokens": 4,
        "completion_tokens": 8,
        "duration_ms": body["data"]["meta"]["duration_ms"],
    }
    assert body["data"]["meta"]["duration_ms"] >= 0
    assert response.headers["X-Request-ID"]


def test_preview_story_plan_validates_request() -> None:
    app = create_app()
    app.dependency_overrides[get_story_planner] = lambda: StoryPlanner(FakeClient())
    response = TestClient(app).post(
        "/api/story-plans/preview", json={"inspiration": "短", "episode_count": 4}
    )
    assert response.status_code == 422
    assert response.json()["message"] == "request validation failed"


def test_preview_requires_configured_model() -> None:
    response = TestClient(create_app()).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )
    assert response.status_code == 503
    assert response.json()["code"] == 50301


def test_preview_rejects_blank_model_key(monkeypatch) -> None:
    monkeypatch.setenv("SCENECHOICE_DEEPSEEK_API_KEY", "   ")
    get_settings.cache_clear()

    response = TestClient(create_app()).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == 503
    assert response.json()["code"] == 50301


def test_preview_maps_provider_authentication_failure_to_configuration_error() -> None:
    app = create_app()
    error = DeepSeekClientError("auth failed", retryable=False, status_code=401)
    app.dependency_overrides[get_story_planner] = lambda: FailingPlanner(error)

    response = TestClient(app).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == 503
    assert response.json()["code"] == 50302
    assert response.json()["message"] == "story model credentials were rejected"


def test_preview_maps_permanent_provider_rejection_to_bad_request() -> None:
    app = create_app()
    error = DeepSeekClientError("request rejected", retryable=False, status_code=400)
    app.dependency_overrides[get_story_planner] = lambda: FailingPlanner(error)

    response = TestClient(app).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == 400
    assert response.json()["code"] == 50202
    assert response.json()["message"] == "story model rejected the request"


@pytest.mark.parametrize(
    ("provider_status", "expected_status", "expected_code", "expected_message"),
    [
        (401, 503, 50302, "story model credentials were rejected"),
        (403, 503, 50302, "story model credentials were rejected"),
        (408, 502, 50201, "story model is temporarily unavailable"),
        (429, 502, 50201, "story model is temporarily unavailable"),
        (500, 502, 50201, "story model is temporarily unavailable"),
        (422, 400, 50202, "story model rejected the request"),
    ],
)
def test_preview_maps_provider_http_statuses(
    provider_status: int,
    expected_status: int,
    expected_code: int,
    expected_message: str,
) -> None:
    app = create_app()
    error = DeepSeekClientError("provider failed", retryable=False, status_code=provider_status)
    app.dependency_overrides[get_story_planner] = lambda: FailingPlanner(error)

    response = TestClient(app).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["message"] == expected_message


def test_preview_maps_exhausted_planning_to_unprocessable_story() -> None:
    app = create_app()
    error = StoryPlanningError("invalid blueprint", attempts=3, issues=["rule failed"])
    app.dependency_overrides[get_story_planner] = lambda: FailingPlanner(error)

    response = TestClient(app).post(
        "/api/story-plans/preview",
        json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42201


def test_openapi_exposes_typed_story_plan_contract() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    operation = schema["paths"]["/api/story-plans/preview"]["post"]
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert success_schema["$ref"].endswith("/StoryPlanPreviewResponse")
    components = schema["components"]["schemas"]
    assert "StoryBlueprint" in components
    assert "StoryPlanMeta" in components
    assert "StoryPlanPreviewData" in components
    assert operation["responses"]["502"]["content"]["application/json"]["schema"]["$ref"].endswith("/ApiResponse")


def test_openapi_documents_permanent_provider_rejection() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    operation = schema["paths"]["/api/story-plans/preview"]["post"]
    response_schema = operation["responses"]["400"]["content"]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/ApiResponse")


def test_story_planning_log_contains_incoming_request_id(caplog) -> None:
    app = create_app()
    app.dependency_overrides[get_story_planner] = lambda: StoryPlanner(FakeClient())

    with caplog.at_level(logging.INFO, logger="app.services.story_planner"):
        response = TestClient(app).post(
            "/api/story-plans/preview",
            headers={"X-Request-ID": "trace-story-123"},
            json={"inspiration": "一个小主播误开麦后被恶意剪辑", "episode_count": 3},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-story-123"
    assert "request_id=trace-story-123" in caplog.text
