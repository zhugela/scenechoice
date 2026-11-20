"""Apply one player choice to a persisted story.

The model writes the blueprint once; every number after that is decided here by
Python (see :mod:`app.services.play_engine`). This module only translates an
engine outcome into the HTTP contract and owns the transaction boundary.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db_session
from app.schemas.response import ApiResponse
from app.schemas.stories import (
    MetricState,
    PlayChoiceRequest,
    PlayOutcomeData,
    PlayOutcomeResponse,
)
from app.services.play_engine import PlayError, advance_story
from app.services.play_errors import (
    PLAY_400_DESCRIPTION,
    PLAY_404_DESCRIPTION,
    PLAY_409_DESCRIPTION,
    PLAY_500_DESCRIPTION,
    play_error_to_app_error,
)


router = APIRouter(prefix="/api/stories", tags=["play"])


@router.post(
    "/{public_id}/play",
    response_model=PlayOutcomeResponse,
    summary="Apply one player choice and advance the story",
    responses={
        400: {"model": ApiResponse, "description": PLAY_400_DESCRIPTION},
        404: {"model": ApiResponse, "description": PLAY_404_DESCRIPTION},
        409: {"model": ApiResponse, "description": PLAY_409_DESCRIPTION},
        500: {"model": ApiResponse, "description": PLAY_500_DESCRIPTION},
    },
)
def play_choice(
    public_id: str,
    request: PlayChoiceRequest,
    session: Session = Depends(get_db_session),
) -> PlayOutcomeResponse:
    try:
        outcome = advance_story(session, public_id, request.choice_key)
    except PlayError as exc:
        # advance_story raises inside its own transaction, so nothing was
        # written; the request-scoped session rolls back when it closes.
        raise play_error_to_app_error(exc) from exc

    session.commit()
    return PlayOutcomeResponse(
        data=PlayOutcomeData(
            public_id=outcome.story_public_id,
            status=outcome.story_status,
            episode_number=outcome.episode_number,
            next_episode_number=outcome.next_episode_number,
            metrics=[
                MetricState(metric_id=key, current_value=value)
                for key, value in outcome.metrics.items()
            ],
            ending_key=outcome.ending_key,
            sequence=outcome.sequence,
        )
    )
