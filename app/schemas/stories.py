"""HTTP contracts for persisted story archives."""

from datetime import datetime
from typing import Literal

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


class StoryListResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: StoryListData
