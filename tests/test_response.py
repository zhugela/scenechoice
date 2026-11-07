from app.schemas.response import ApiResponse


def test_ok_response_keeps_data() -> None:
    response = ApiResponse.ok({"episode_id": 1})

    assert response.model_dump() == {
        "code": 0,
        "message": "ok",
        "data": {"episode_id": 1},
    }


def test_error_response_uses_requested_code() -> None:
    response = ApiResponse.error("story not found", code=404)

    assert response.model_dump() == {
        "code": 404,
        "message": "story not found",
        "data": None,
    }
