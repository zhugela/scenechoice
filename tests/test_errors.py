from fastapi.testclient import TestClient

from app.errors import AppError
from app.main import create_app


def test_app_error_uses_unified_response() -> None:
    test_app = create_app()

    @test_app.get("/missing-story")
    def missing_story() -> None:
        raise AppError("story not found", code=40401, status_code=404)

    response = TestClient(test_app).get("/missing-story")

    assert response.status_code == 404
    assert response.json() == {
        "code": 40401,
        "message": "story not found",
        "data": None,
    }
    assert "X-Request-ID" in response.headers


def test_unknown_error_hides_internal_details() -> None:
    test_app = create_app()

    @test_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password should not leak")

    response = TestClient(test_app).get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "code": 500,
        "message": "internal server error",
        "data": None,
    }
    assert "database password" not in response.text
    assert "X-Request-ID" in response.headers


def test_framework_404_uses_unified_response() -> None:
    response = TestClient(create_app()).get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "code": 404,
        "message": "Not Found",
        "data": None,
    }


def test_validation_error_uses_unified_response() -> None:
    test_app = create_app()

    @test_app.get("/episodes")
    def get_episode(episode_id: int) -> dict[str, int]:
        return {"episode_id": episode_id}

    response = TestClient(test_app).get("/episodes", params={"episode_id": "wrong"})

    assert response.status_code == 422
    assert response.json() == {
        "code": 422,
        "message": "request validation failed",
        "data": None,
    }
    assert "X-Request-ID" in response.headers
