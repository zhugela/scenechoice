from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterBlueprint(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=30)
    role: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=200)
    secret: str = Field(min_length=1, max_length=200)
    personality: list[str] = Field(min_length=1, max_length=3)


class MetricBlueprint(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=150)
    initial_value: int = Field(ge=0, le=100)
    low_label: str = Field(min_length=1, max_length=30)
    high_label: str = Field(min_length=1, max_length=30)


class MetricEffect(StrictModel):
    metric_id: str
    delta: int = Field(ge=-30, le=30)


class ChoiceBlueprint(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1, max_length=120)
    effects: list[MetricEffect] = Field(min_length=1, max_length=2)
    consequence_hint: str = Field(min_length=1, max_length=200)


class EpisodeBlueprint(StrictModel):
    number: int = Field(ge=1, le=5)
    objective: str = Field(min_length=1, max_length=200)
    conflict: str = Field(min_length=1, max_length=200)
    character_ids: list[str] = Field(min_length=1, max_length=4)
    required_events: list[str] = Field(min_length=1, max_length=3)
    cliffhanger: str | None = Field(default=None, max_length=200)
    resolution: str | None = Field(default=None, max_length=300)
    choices: list[ChoiceBlueprint] = Field(min_length=2, max_length=2)


class EndingCondition(StrictModel):
    metric_id: str
    operator: Literal["lt", "lte", "gt", "gte", "eq"]
    value: int = Field(ge=0, le=100)


class EndingBlueprint(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=60)
    summary: str = Field(min_length=1, max_length=300)
    category: Literal["low", "high", "mixed"]
    conditions: list[EndingCondition] = Field(min_length=1, max_length=2)
    priority: int = Field(ge=1)


class StoryBlueprint(StrictModel):
    title: str = Field(min_length=1, max_length=60)
    logline: str = Field(min_length=1, max_length=200)
    genre: str = Field(min_length=1, max_length=40)
    theme: str = Field(min_length=1, max_length=100)
    episode_count: Literal[3, 5]
    characters: list[CharacterBlueprint] = Field(min_length=2, max_length=4)
    metrics: list[MetricBlueprint] = Field(min_length=2, max_length=2)
    episodes: list[EpisodeBlueprint] = Field(min_length=3, max_length=5)
    endings: list[EndingBlueprint] = Field(min_length=3)


class CreateStoryPlanRequest(StrictModel):
    inspiration: str = Field(min_length=5, max_length=500)
    episode_count: Literal[3, 5] = 3


class StoryPlanMeta(StrictModel):
    attempts: int = Field(ge=1)
    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class StoryPlanPreviewData(StrictModel):
    blueprint: StoryBlueprint
    meta: StoryPlanMeta


class StoryPlanPreviewResponse(StrictModel):
    code: int = 0
    message: str = "ok"
    data: StoryPlanPreviewData
