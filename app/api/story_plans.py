from fastapi import APIRouter, Depends

from app.clients.deepseek import DeepSeekClientError
from app.dependencies import get_story_planner
from app.errors import AppError
from app.schemas.response import ApiResponse
from app.schemas.story_blueprint import (
    CreateStoryPlanRequest,
    StoryPlanMeta,
    StoryPlanPreviewData,
    StoryPlanPreviewResponse,
)
from app.services.provider_errors import (
    STORY_MODEL_502_DESCRIPTION,
    STORY_MODEL_503_DESCRIPTION,
    provider_error_to_app_error,
)
from app.services.story_planner import StoryPlanner, StoryPlanningError


router = APIRouter(prefix="/api/story-plans", tags=["story-plans"])


@router.post(
    "/preview",
    response_model=StoryPlanPreviewResponse,
    summary="Generate a validated interactive-story blueprint",
    description="Generate a complete 3- or 5-episode blueprint without saving it.",
    responses={
        400: {"model": ApiResponse, "description": "Story model rejected the request"},
        422: {"model": ApiResponse, "description": "Invalid request or blueprint generation failure"},
        502: {
            "model": ApiResponse,
            "description": STORY_MODEL_502_DESCRIPTION,
        },
        503: {
            "model": ApiResponse,
            "description": STORY_MODEL_503_DESCRIPTION,
        },
    },
)
async def preview_story_plan(
    request: CreateStoryPlanRequest,
    planner: StoryPlanner = Depends(get_story_planner),
) -> StoryPlanPreviewResponse:
    try:
        result = await planner.plan(request.inspiration, request.episode_count)
    except DeepSeekClientError as exc:
        raise provider_error_to_app_error(exc) from exc
    except StoryPlanningError as exc:
        raise AppError("unable to create a valid story plan", code=42201, status_code=422) from exc
    return StoryPlanPreviewResponse(
        data=StoryPlanPreviewData(
            blueprint=result.blueprint,
            meta=StoryPlanMeta(
                attempts=result.attempts,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                duration_ms=result.duration_ms,
            ),
        )
    )
