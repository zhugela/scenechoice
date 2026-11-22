"""Generate, persist, list, and restore story archives."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.clients.deepseek import DeepSeekClientError
from app.dependencies import get_db_session, get_story_planner
from app.errors import (
    AppError,
    IDEMPOTENCY_IN_PROGRESS,
    IDEMPOTENCY_KEY_REUSED,
    STORY_ARCHIVE_CORRUPTED,
    STORY_NOT_FOUND,
    STORY_PLAN_INVALID,
    STORY_VERSION_UNSUPPORTED,
)
from app.models import Story
from app.models.base import as_utc
from app.schemas.response import ApiResponse
from app.schemas.stories import (
    CreateStoryRequest,
    EpisodeState,
    MetricState,
    StoryCreatedData,
    StoryCreatedResponse,
    StoryDetailData,
    StoryDetailResponse,
    StoryListData,
    StoryListResponse,
    StoryStateChangeData,
    StoryStateData,
    StoryStateResponse,
    StorySummary,
)
from app.services.idempotency import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    STORIES_CREATE_SCOPE,
    claim as claim_idempotency,
    complete as complete_idempotency,
    release as release_idempotency,
    request_fingerprint,
)
from app.services.provider_errors import (
    STORY_MODEL_502_DESCRIPTION,
    STORY_MODEL_503_DESCRIPTION,
    provider_error_to_app_error,
)
from app.services.story_planner import StoryPlanner, StoryPlanningError
from app.services.story_store import (
    BlueprintCorruptedError,
    BlueprintStorageError,
    BlueprintVersionError,
    list_stories,
    load_blueprint,
    load_story_state,
    save_blueprint,
)


router = APIRouter(prefix="/api/stories", tags=["stories"])


def _summary(story: Story) -> StorySummary:
    return StorySummary(
        public_id=story.public_id,
        title=story.title,
        logline=story.logline,
        genre=story.genre,
        theme=story.theme,
        episode_count=story.episode_count,
        status=story.status,
        created_at=as_utc(story.created_at),
        updated_at=as_utc(story.updated_at),
    )


@router.post(
    "",
    response_model=StoryCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and persist a complete story",
    responses={
        400: {"model": ApiResponse, "description": "Story model rejected the request"},
        422: {"model": ApiResponse, "description": "Invalid request or generation failure"},
        409: {
            "model": ApiResponse,
            "description": "Idempotency-Key reused with a different body or still in progress",
        },
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
async def create_story(
    request: CreateStoryRequest,
    planner: StoryPlanner = Depends(get_story_planner),
    session: Session = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StoryCreatedResponse | JSONResponse:
    # FastAPI injects a string (or None) for real requests. The isinstance guard
    # keeps direct calls from tests, which leave the dependency default in
    # place, working without a ``Header`` object leaking into the code path.
    key = (idempotency_key if isinstance(idempotency_key, str) else "").strip()
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        # Same envelope as FastAPI's own request validation: the caller sent an
        # unusable header, not a conflict with stored state.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Idempotency-Key must be at most "
                f"{IDEMPOTENCY_KEY_MAX_LENGTH} characters"
            ),
        )

    # No key means the pre-batch behavior exactly: every call generates and
    # persists a fresh archive.
    if not key:
        return await _plan_and_store(request, planner, session)

    fingerprint = request_fingerprint(request.model_dump())
    claim = claim_idempotency(
        session,
        scope=STORIES_CREATE_SCOPE,
        key=key,
        fingerprint=fingerprint,
    )

    if claim.outcome == "mismatch":
        raise AppError(
            "this Idempotency-Key was already used with a different request",
            code=IDEMPOTENCY_KEY_REUSED,
            status_code=409,
        )
    if claim.outcome == "in_progress":
        raise AppError(
            "a request with this Idempotency-Key is still in progress",
            code=IDEMPOTENCY_IN_PROGRESS,
            status_code=409,
        )

    record = claim.record
    if record is None:
        # Defensive: replay/claimed always carry a record. Treat a missing one
        # as "still in progress" so a transient race never becomes a 500.
        raise AppError(
            "a request with this Idempotency-Key is still in progress",
            code=IDEMPOTENCY_IN_PROGRESS,
            status_code=409,
        )

    if claim.outcome == "replay":
        # Replay the original status and body byte-for-byte. Re-serializing the
        # Pydantic model here would risk drifting from what the first caller
        # actually received.
        return JSONResponse(
            status_code=record.status_code or status.HTTP_201_CREATED,
            content=record.response_body,
            headers={"Idempotent-Replay": "true"},
        )

    # claim.outcome == "claimed"
    try:
        payload = await _plan_and_store(request, planner, session)
        complete_idempotency(
            session,
            record,
            status_code=status.HTTP_201_CREATED,
            body=payload.model_dump(mode="json"),
            token=claim.token,
        )
    except Exception:
        # Generation or persistence failed after the claim was taken. Delete the
        # claim so an immediate retry with the same key does not look like a
        # request that is still running.
        release_idempotency(session, record, token=claim.token)
        raise
    return payload


async def _plan_and_store(
    request: CreateStoryRequest,
    planner: StoryPlanner,
    session: Session,
) -> StoryCreatedResponse:
    """Generate one blueprint and persist it; shared by both request paths."""
    try:
        result = await planner.plan(request.inspiration, request.episode_count)
    except DeepSeekClientError as exc:
        raise provider_error_to_app_error(exc) from exc
    except StoryPlanningError as exc:
        raise AppError(
            "unable to create a valid story plan",
            code=STORY_PLAN_INVALID,
            status_code=422,
        ) from exc

    try:
        story = save_blueprint(session, result.blueprint)
    except BlueprintStorageError as exc:
        raise AppError(
            "unable to create a valid story plan",
            code=STORY_PLAN_INVALID,
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
    "/{public_id}/state",
    response_model=StoryStateResponse,
    summary="Restore mutable story play progress",
    responses={404: {"model": ApiResponse, "description": "Story not found"}},
)
def get_story_state(
    public_id: str,
    change_limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> StoryStateResponse:
    loaded = load_story_state(session, public_id, change_limit=change_limit)
    if loaded is None:
        raise AppError("story not found", code=STORY_NOT_FOUND, status_code=404)

    story, recent_changes = loaded
    return StoryStateResponse(
        data=StoryStateData(
            public_id=story.public_id,
            status=story.status,
            metrics=[
                MetricState(metric_id=metric.key, current_value=metric.current_value)
                for metric in story.metrics
            ],
            episodes=[
                EpisodeState(number=episode.number, status=episode.status)
                for episode in story.episodes
            ],
            last_sequence=recent_changes[0].sequence if recent_changes else 0,
            recent_state_changes=[
                StoryStateChangeData(
                    sequence=change.sequence,
                    entity_type=change.entity_type,
                    entity_key=change.entity_key,
                    event_type=change.event_type,
                    before_state=change.before_state,
                    after_state=change.after_state,
                    source=change.source,
                    occurred_at=as_utc(change.occurred_at),
                )
                for change in recent_changes
            ],
        )
    )


@router.get(
    "/{public_id}",
    response_model=StoryDetailResponse,
    summary="Restore a complete story blueprint",
    responses={
        404: {"model": ApiResponse, "description": "Story not found"},
        409: {
            "model": ApiResponse,
            "description": "Story archive uses an unsupported blueprint version (40902)",
        },
        500: {
            "model": ApiResponse,
            "description": "Stored story archive is corrupted (50003)",
        },
    },
)
def get_story(
    public_id: str,
    session: Session = Depends(get_db_session),
) -> StoryDetailResponse:
    try:
        blueprint = load_blueprint(session, public_id)
    except BlueprintVersionError as exc:
        raise AppError(
            f"this story archive uses blueprint version {exc.stored}; "
            f"this server supports version {exc.supported}",
            code=STORY_VERSION_UNSUPPORTED,
            status_code=409,
        ) from exc
    except BlueprintCorruptedError as exc:
        raise AppError(
            "this story archive is corrupted and cannot be opened",
            code=STORY_ARCHIVE_CORRUPTED,
            status_code=500,
        ) from exc
    if blueprint is None:
        raise AppError("story not found", code=STORY_NOT_FOUND, status_code=404)
    return StoryDetailResponse(
        data=StoryDetailData(public_id=public_id, blueprint=blueprint)
    )
