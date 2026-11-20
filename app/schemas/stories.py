"""HTTP contracts for persisted story archives."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.story_blueprint import StoryBlueprint


class CreateStoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspiration: str = Field(min_length=5, max_length=500)
    episode_count: Literal[3, 5] = 3


class StorySummary(BaseModel):
    public_id: str
    title: str
    logline: str
    genre: str
    theme: str
    episode_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class StoryCreatedData(StorySummary):
    pass


class StoryDetailData(BaseModel):
    public_id: str
    blueprint: StoryBlueprint


class MetricState(BaseModel):
    metric_id: str
    current_value: int = Field(ge=0, le=100)


class EpisodeState(BaseModel):
    number: int = Field(ge=1, le=5)
    status: str


class StoryStateChangeData(BaseModel):
    sequence: int = Field(ge=1)
    entity_type: str
    entity_key: str
    event_type: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    source: str
    occurred_at: datetime


class StoryStateData(BaseModel):
    public_id: str
    status: str
    metrics: list[MetricState]
    episodes: list[EpisodeState]
    last_sequence: int = Field(ge=0)
    recent_state_changes: list[StoryStateChangeData]


class StoryListData(BaseModel):
    items: list[StorySummary]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class StoryCreatedResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: StoryCreatedData


class StoryDetailResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: StoryDetailData


class StoryStateResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: StoryStateData


class StoryListResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: StoryListData


class PlayChoiceRequest(BaseModel):
    """One player action. ``extra="forbid"`` so a typo'd field is a 422, not a silent no-op."""

    model_config = ConfigDict(extra="forbid")

    choice_key: str = Field(min_length=1, max_length=64)


class PlayOutcomeData(BaseModel):
    """What one accepted choice did, in the order the client should show it."""

    public_id: str
    status: str
    episode_number: int = Field(ge=1, le=5)
    next_episode_number: int | None = Field(default=None, ge=1, le=5)
    metrics: list[MetricState]
    ending_key: str | None = None
    sequence: int = Field(ge=0)


class PlayOutcomeResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: PlayOutcomeData
