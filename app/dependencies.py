from app.clients.deepseek import DeepSeekClient
from app.config import get_settings
from app.errors import AppError
from app.services.story_planner import StoryPlanner


def get_story_planner() -> StoryPlanner:
    settings = get_settings()
    if settings.deepseek_api_key is None or not settings.deepseek_api_key.get_secret_value().strip():
        raise AppError("story planning service is not configured", code=50301, status_code=503)
    client = DeepSeekClient(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout=settings.deepseek_timeout_seconds,
        max_tokens=settings.deepseek_max_tokens,
    )
    return StoryPlanner(
        client,
        max_attempts=settings.story_planning_max_attempts,
        retry_base_seconds=settings.story_planning_retry_base_seconds,
        retry_max_seconds=settings.story_planning_retry_max_seconds,
    )
