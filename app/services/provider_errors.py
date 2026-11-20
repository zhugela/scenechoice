"""Translate provider failures into SceneChoice's public error contract.

Lives in the service layer because the decision here is product policy: which
HTTP status and application error code we expose to *our* clients for a given
provider failure. The provider client stays unaware of our public error codes,
and both story routes share this single mapping so the preview and persist
contracts cannot drift apart.
"""

from app.clients.deepseek import DeepSeekClientError, is_retryable_status
from app.errors import (
    AppError,
    STORY_MODEL_CREDENTIALS_REJECTED,
    STORY_MODEL_INSUFFICIENT_BALANCE,
    STORY_MODEL_NOT_CONFIGURED,
    STORY_MODEL_PROTOCOL_ERROR,
    STORY_MODEL_REQUEST_REJECTED,
    STORY_MODEL_UNAVAILABLE,
    STORY_PLAN_INVALID,
)

# OpenAPI descriptions for the story routes that expose this contract. They live
# next to the mapping so the documented error codes cannot drift from the codes
# the mapping actually returns. The numbers are interpolated rather than typed
# again, so the rendered description says exactly what the mapping returns while
# ``app/errors.py`` stays the only place the digits exist in this package.
STORY_MODEL_502_DESCRIPTION = (
    f"Story model is unavailable ({STORY_MODEL_UNAVAILABLE}) or returned "
    f"an unexpected protocol status ({STORY_MODEL_PROTOCOL_ERROR})"
)
STORY_MODEL_503_DESCRIPTION = (
    f"Story model is not configured ({STORY_MODEL_NOT_CONFIGURED}), "
    f"credentials were rejected ({STORY_MODEL_CREDENTIALS_REJECTED}), "
    f"or the account has insufficient balance ({STORY_MODEL_INSUFFICIENT_BALANCE})"
)


def provider_error_to_app_error(exc: DeepSeekClientError) -> AppError:
    """Return the application error that should surface for a provider failure.

    Callers must use ``raise provider_error_to_app_error(exc) from exc`` so the
    original provider error stays attached as ``__cause__``.
    """
    if exc.status_code in {401, 403}:
        return AppError(
            "story model credentials were rejected",
            code=STORY_MODEL_CREDENTIALS_REJECTED,
            status_code=503,
        )
    if exc.status_code == 402:
        return AppError(
            "story model account has insufficient balance",
            code=STORY_MODEL_INSUFFICIENT_BALANCE,
            status_code=503,
        )
    if exc.status_code == 200:
        # A successful HTTP status with an invalid body means generation failed,
        # not that the provider itself is currently unavailable.
        return AppError(
            "unable to create a valid story plan",
            code=STORY_PLAN_INVALID,
            status_code=422,
        )
    if (
        exc.status_code is not None
        and 400 <= exc.status_code < 500
        and not is_retryable_status(exc.status_code)
    ):
        return AppError(
            "story model rejected the request",
            code=STORY_MODEL_REQUEST_REJECTED,
            status_code=400,
        )
    if exc.status_code is not None and exc.status_code < 400:
        return AppError(
            "story model returned an unexpected protocol status",
            code=STORY_MODEL_PROTOCOL_ERROR,
            status_code=502,
        )
    return AppError(
        "story model is temporarily unavailable",
        code=STORY_MODEL_UNAVAILABLE,
        status_code=502,
    )
