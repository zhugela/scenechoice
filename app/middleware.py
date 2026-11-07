import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.exception_handlers import error_response
from app.request_context import reset_request_id, set_request_id


logger = logging.getLogger(__name__)


async def add_request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID", "").strip() or uuid4().hex
    request.state.request_id = request_id
    context_token = set_request_id(request_id)

    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled exception request_id=%s", request_id)
            response = error_response(
                status_code=500,
                code=500,
                message="internal server error",
            )

        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        reset_request_id(context_token)
