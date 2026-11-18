"""Translate provider failures into SceneChoice's public error contract.

Lives in the service layer because the decision here is product policy: which
HTTP status and application error code we expose to *our* clients for a given
provider failure. The provider client stays unaware of our public error codes,
and both story routes share this single mapping so the preview and persist
contracts cannot drift apart.
"""

from app.clients.deepseek import DeepSeekClientError, is_retryable_status
from app.errors import AppError

# OpenAPI descriptions for the story routes that expose this contract. They live
# next to the mapping so the documented error codes cannot drift from the codes
# the mapping actually returns.
STORY_MODEL_502_DESCRIPTION = (
    "Story model is unavailable (50201) or returned an unexpected protocol status (50204)"
)
STORY_MODEL_503_DESCRIPTION = (
    "Story model is not configured (50301), credentials were rejected (50302), "
    "or the account has insufficient balance (50303)"
)


def provider_error_to_app_error(exc: DeepSeekClientError) -> AppError:
    """Return the application error that should surface for a provider failure.

    Callers must use ``raise provider_error_to_app_error(exc) from exc`` so the
    original provider error stays attached as ``__cause__``.
    """
    if exc.status_code in {401, 403}:
        return AppError(
            "story model credentials were rejected",
            code=50302,
            status_code=503,
        )
    if exc.status_code == 402:
        return AppError(
            "story model account has insufficient balance",
            code=50303,
            status_code=503,
        )
    if exc.status_code == 200:
        # A successful HTTP status with an invalid body means generation failed,
        # not that the provider itself is currently unavailable.
        return AppError(
            "unable to create a valid story plan",
            code=42201,
            status_code=422,
        )
    if (
        exc.status_code is not None
        and 400 <= exc.status_code < 500
        and not is_retryable_status(exc.status_code)
    ):
        return AppError(
            "story model rejected the request",
            code=50202,
            status_code=400,
        )
    if exc.status_code is not None and exc.status_code < 400:
        return AppError(
            "story model returned an unexpected protocol status",
            code=50204,
            status_code=502,
        )
    return AppError(
        "story model is temporarily unavailable",
        code=50201,
        status_code=502,
    )
