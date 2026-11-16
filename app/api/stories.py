"""Generate, persist, list, and restore story archives."""

from typing import NoReturn

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.clients.deepseek import DeepSeekClientError, is_retryable_status
from app.dependencies import get_db_session, get_story_planner
from app.errors import AppError
from app.models import Story
from app.schemas.response import ApiResponse
from app.schemas.stories import (
    CreateStoryRequest,
    StoryCreatedData,
    StoryCreatedResponse,
    StoryDetailData,
    StoryDetailResponse,
    StoryListData,
    StoryListResponse,
    StorySummary,
)
from app.services.story_planner import StoryPlanner, StoryPlanningError
from app.services.story_store import BlueprintStorageError, list_stories, load_blueprint, save_blueprint


router = APIRouter(prefix="/api/stories", tags=["stories"])


def _raise_planning_error(exc: Exception) -> NoReturn:
    """Use the same provider-error meanings as the M1 preview contract."""
    if isinstance(exc, DeepSeekClientError):
        if exc.status_code in {401, 403}:
            raise AppError(
                "story model credentials were rejected",
                code=50302,
                status_code=503,
            )
        if exc.status_code == 402:
            raise AppError(
                "story model account has insufficient balance",
                code=50303,
                status_code=503,
            )
        if exc.status_code == 200:
            raise AppError(
                "unable to create a valid story plan",
                code=42201,
                status_code=422,
            )
        if (
            exc.status_code is not None
            and 400 <= exc.status_code < 500
            and not is_retryable_status(exc.status_code)
        ):
            raise AppError(
                "story model rejected the request",
                code=50202,
                status_code=400,
            )
        if exc.status_code is not None and exc.status_code < 400:
            raise AppError(
                "story model returned an unexpected protocol status",
                code=50204,
                status_code=502,
            )
        raise AppError(
            "story model is temporarily unavailable",
            code=50201,
            status_code=502,
        )
    raise AppError(
        "unable to create a valid story plan",
        code=42201,
        status_code=422,
    )


def _summary(story: Story) -> StorySummary:
    return StorySummary(
        public_id=story.public_id,
        title=story.title,
        logline=story.logline,
        genre=story.genre,
        theme=story.theme,
        episode_count=story.episode_count,
        status=story.status,
        created_at=story.created_at,
        updated_at=story.updated_at,
    )


@router.post(
    "",
    response_model=StoryCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and persist a complete story",
    responses={
        400: {"model": ApiResponse, "description": "Story model rejected the request"},
        422: {"model": ApiResponse, "description": "Invalid request or generation failure"},
        502: {
            "model": ApiResponse,
            "description": (
                "Story model is unavailable (50201) or returned an unexpected protocol status (50204)"
            ),
        },
        503: {
            "model": ApiResponse,
            "description": (
                "Story model is not configured (50301), credentials were rejected (50302), "
                "or the account has insufficient balance (50303)"
            ),
        },
    },
)
async def create_story(
    request: CreateStoryRequest,
    planner: StoryPlanner = Depends(get_story_planner),
    session: Session = Depends(get_db_session),
) -> StoryCreatedResponse:
    try:
        result = await planner.plan(request.inspiration, request.episode_count)
    except (DeepSeekClientError, StoryPlanningError) as exc:
        _raise_planning_error(exc)

    try:
        story = save_blueprint(session, result.blueprint)
    except BlueprintStorageError as exc:
        raise AppError(
            "unable to create a valid story plan",
            code=42201,
            status_code=422,
        ) from exc
    return StoryCreatedResponse(data=StoryCreatedData(**_summary(story).model_dump()))


@router.get(
    "",
    response_model=StoryListResponse,
    summary="List persisted story summaries",
)
def get_stories(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> StoryListResponse:
    stories, total = list_stories(session, offset=offset, limit=limit)
    return StoryListResponse(
        data=StoryListData(
            items=[_summary(story) for story in stories],
            total=total,
            offset=offset,
            limit=limit,
        )
    )


@router.get(
    "/{public_id}",
    response_model=StoryDetailResponse,
    summary="Restore a complete story blueprint",
    responses={404: {"model": ApiResponse, "description": "Story not found"}},
)
def get_story(
    public_id: str,
    session: Session = Depends(get_db_session),
) -> StoryDetailResponse:
    blueprint = load_blueprint(session, public_id)
    if blueprint is None:
        raise AppError("story not found", code=40401, status_code=404)
    return StoryDetailResponse(
        data=StoryDetailData(public_id=public_id, blueprint=blueprint)
    )
