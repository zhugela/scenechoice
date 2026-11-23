"""Serve the narration of one player event.

The first request for an event generates and stores the text; every later
request replays the stored row without calling the provider. This route only
translates failures and assembles the response — :mod:`app.services.narrator`
owns the cache, the repair loop, and the transaction.

One play action writes several player-event rows, all narrated by one text.
The request may use any of their sequences; the response returns the turn
anchor (the ``choice_selected`` sequence), so clients learn the single value
that addresses that turn.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.clients.deepseek import DeepSeekClient, DeepSeekClientError
from app.config import get_settings
from app.dependencies import get_db_session
from app.errors import (
    AppError,
    NARRATION_EVENT_NOT_FOUND,
    NARRATION_REJECTED,
    STORY_MODEL_NOT_CONFIGURED,
    STORY_NOT_FOUND,
    STORY_VERSION_UNSUPPORTED,
)
from app.schemas.response import ApiResponse
from app.services.narrator import (
    CompletionClient,
    NarrationEventNotFound,
    NarrationRejected,
    NarrationStoryNotFound,
    generate,
)
from app.services.provider_errors import (
    STORY_MODEL_502_DESCRIPTION,
    STORY_MODEL_503_DESCRIPTION,
    provider_error_to_app_error,
)
from app.services.story_store import BlueprintVersionError


router = APIRouter(prefix="/api/stories", tags=["narrations"])


# Descriptions are built from the shared constants so the documented code and
# the returned code are one fact, and the digits exist only in ``app/errors.py``.
NARRATION_404_DESCRIPTION = (
    f"Story not found ({STORY_NOT_FOUND}) or the event has no narration "
    f"({NARRATION_EVENT_NOT_FOUND})"
)
NARRATION_409_DESCRIPTION = (
    "Story archive uses an unsupported blueprint version "
    f"({STORY_VERSION_UNSUPPORTED})"
)
NARRATION_422_DESCRIPTION = (
    "Narration failed validation after 3 attempts "
    f"({NARRATION_REJECTED})"
)


class NarrationData(BaseModel):
    public_id: str
    # The turn anchor (this turn's ``choice_selected`` sequence), not
    # necessarily the sequence the caller used to ask for the narration.
    sequence: int = Field(ge=1)
    text: str
    model: str


class NarrationResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: NarrationData


def get_narration_client() -> CompletionClient:
    """Build the provider client, or fail with the shared not-configured code."""
    settings = get_settings()
    api_key = settings.deepseek_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise AppError(
            "narration service is not configured",
            code=STORY_MODEL_NOT_CONFIGURED,
            status_code=503,
        )
    return DeepSeekClient(
        api_key=api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
    )


@router.get(
    "/{public_id}/narrations/{sequence}",
    response_model=NarrationResponse,
    summary="Read the narration of one player event, generating it on first read",
    responses={
        404: {"model": ApiResponse, "description": NARRATION_404_DESCRIPTION},
        409: {"model": ApiResponse, "description": NARRATION_409_DESCRIPTION},
        422: {"model": ApiResponse, "description": NARRATION_422_DESCRIPTION},
        502: {"model": ApiResponse, "description": STORY_MODEL_502_DESCRIPTION},
        503: {"model": ApiResponse, "description": STORY_MODEL_503_DESCRIPTION},
    },
)
async def get_narration(
    public_id: str,
    sequence: int,
    session: Session = Depends(get_db_session),
    client: CompletionClient = Depends(get_narration_client),
) -> NarrationResponse:
    try:
        narration = await generate(
            session,
            public_id,
            sequence,
            client=client,
        )
    except NarrationStoryNotFound as exc:
        raise AppError(
            "story not found",
            code=STORY_NOT_FOUND,
            status_code=404,
        ) from exc
    except NarrationEventNotFound as exc:
        raise AppError(
            "this event has no narration",
            code=NARRATION_EVENT_NOT_FOUND,
            status_code=404,
        ) from exc
    except BlueprintVersionError as exc:
        raise AppError(
            f"this story archive uses blueprint version {exc.stored}; "
            f"this server supports version {exc.supported}",
            code=STORY_VERSION_UNSUPPORTED,
            status_code=409,
        ) from exc
    except NarrationRejected as exc:
        raise AppError(
            "narration failed validation after 3 attempts",
            code=NARRATION_REJECTED,
            status_code=422,
        ) from exc
    except DeepSeekClientError as exc:
        raise provider_error_to_app_error(exc) from exc

    return NarrationResponse(
        data=NarrationData(
            public_id=public_id,
            sequence=narration.sequence,
            text=narration.text,
            model=narration.model,
        )
    )
