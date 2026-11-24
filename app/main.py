from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.api.narrations import router as narrations_router
from app.api.play import router as play_router
from app.api.stories import router as stories_router
from app.api.story_plans import router as story_plans_router
from app.errors import AppError
from app.exception_handlers import (
    handle_app_error,
    handle_http_error,
    handle_validation_error,
)
from app.middleware import add_request_context
from app.schemas.response import ApiResponse


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, debug=settings.debug)

    application.middleware("http")(add_request_context)
    application.add_exception_handler(AppError, handle_app_error)
    application.add_exception_handler(HTTPException, handle_http_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.include_router(story_plans_router)
    application.include_router(stories_router)
    application.include_router(play_router)
    application.include_router(narrations_router)

    @application.get("/health", response_model=ApiResponse)
    def health() -> ApiResponse:
        return ApiResponse.ok({"status": "ok"})

    return application


app = create_app()
