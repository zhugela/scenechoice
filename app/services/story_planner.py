import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from app.clients.deepseek import DeepSeekClientError, LlmReply
from app.prompts.story_planning import initial_messages, repair_messages
from app.request_context import get_request_id
from app.schemas.story_blueprint import StoryBlueprint
from app.services.blueprint_validator import BlueprintValidator


class CompletionClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> LlmReply: ...


class StoryPlanningError(RuntimeError):
    def __init__(self, message: str, *, attempts: int, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.issues = list(issues or [])


@dataclass(frozen=True)
class PlanningResult:
    blueprint: StoryBlueprint
    attempts: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int


class StoryPlanner:
    def __init__(
        self,
        client: CompletionClient,
        *,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.5,
        retry_max_seconds: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.sleep = sleep
        self.validator = BlueprintValidator()

    def _retry_delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        requested_delay = (
            retry_after_seconds
            if retry_after_seconds is not None
            else self.retry_base_seconds * (2 ** (attempt - 1))
        )
        return min(requested_delay, self.retry_max_seconds)

    async def plan(self, inspiration: str, episode_count: int) -> PlanningResult:
        started = time.perf_counter()
        base_messages = initial_messages(inspiration, episode_count)
        messages = base_messages
        prompt_tokens = completion_tokens = 0
        model = "unknown"
        last_output = ""
        last_issues = ["model did not return a valid blueprint"]

        for attempt in range(1, self.max_attempts + 1):
            try:
                reply = await self.client.complete(messages)
            except DeepSeekClientError as exc:
                logging.getLogger(__name__).warning(
                    "story_planning model_error request_id=%s attempt=%s retryable=%s status_code=%s retry_after_seconds=%s duration_ms=%s",
                    get_request_id(),
                    attempt,
                    exc.retryable,
                    exc.status_code,
                    exc.retry_after_seconds,
                    round((time.perf_counter() - started) * 1000),
                )
                if not exc.retryable or attempt == self.max_attempts:
                    raise
                await self.sleep(self._retry_delay(attempt, exc.retry_after_seconds))
                continue
            model = reply.model
            prompt_tokens += reply.prompt_tokens
            completion_tokens += reply.completion_tokens
            last_output = reply.content
            try:
                blueprint = StoryBlueprint.model_validate_json(reply.content)
                last_issues = [issue.as_prompt_line() for issue in self.validator.validate(blueprint)]
                if blueprint.episode_count != episode_count:
                    last_issues.append("episode_count: must match the requested episode count")
                if not last_issues:
                    logging.getLogger(__name__).info(
                        "story_planning success request_id=%s model=%s attempts=%s duration_ms=%s prompt_tokens=%s completion_tokens=%s",
                        get_request_id(),
                        model,
                        attempt,
                        round((time.perf_counter() - started) * 1000),
                        prompt_tokens,
                        completion_tokens,
                    )
                    return PlanningResult(
                        blueprint=blueprint,
                        attempts=attempt,
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        duration_ms=round((time.perf_counter() - started) * 1000),
                    )
            except ValidationError as exc:
                last_issues = [
                    f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                    for item in exc.errors(include_url=False)
                ]
            if attempt < self.max_attempts:
                logging.getLogger(__name__).warning(
                    "story_planning validation_error request_id=%s model=%s attempt=%s issue_count=%s issues=%s",
                    get_request_id(),
                    model,
                    attempt,
                    len(last_issues),
                    " | ".join(last_issues[:10]),
                )
                messages = repair_messages(base_messages, last_output, last_issues)

        logging.getLogger(__name__).warning(
            "story_planning failure request_id=%s model=%s attempts=%s issue_count=%s issues=%s",
            get_request_id(),
            model,
            self.max_attempts,
            len(last_issues),
            " | ".join(last_issues[:10]),
        )
        raise StoryPlanningError(
            "story blueprint failed validation",
            attempts=self.max_attempts,
            issues=last_issues,
        )
