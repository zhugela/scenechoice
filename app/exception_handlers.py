from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.errors import AppError
from app.schemas.response import ApiResponse


def error_response(*, status_code: int, code: int, message: str) -> JSONResponse:
    payload = ApiResponse.error(message=message, code=code)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(
        status_code=exc.status_code,
        code=exc.status_code,
        message=str(exc.detail),
    )


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        status_code=422,
        code=422,
        message="request validation failed",
    )
