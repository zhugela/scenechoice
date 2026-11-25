from dataclasses import dataclass
from typing import Any

import httpx


# Single source of truth for "which upstream HTTP status codes are transient and
# worth retrying". Both the client (the retry decision) and the API layer (the
# temporary-vs-permanent error mapping) must derive from this predicate instead
# of each hardcoding their own copy. Lives here, in the client module, because
# this is provider HTTP-error semantics, and the API already imports the error
# type from this module — so the contract has a single home without a new layer.
_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429})


def is_retryable_status(status_code: int) -> bool:
    """Return True when an HTTP status code denotes a transient, retryable failure."""
    return status_code in _RETRYABLE_HTTP_STATUS_CODES or status_code >= 500


class DeepSeekClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, seconds)


@dataclass(frozen=True)
class LlmReply:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        max_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.transport = transport

    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> LlmReply:
        """Ask the model for a completion.

        ``json_mode`` maps to the provider's ``response_format`` switch. It must
        stay a per-call choice: the story planner needs structured JSON, while
        narration needs prose. Forcing JSON on prose measurably degenerates — the
        model answers with a whitespace-only body (observed: 176 completion
        tokens, all spaces) and the narration validator rejects it as "0 汉字".
        """
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            request_body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_body,
                )
                response.raise_for_status()
                payload: Any = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response payload must be an object")
            choices = payload.get("choices")
            first_choice = choices[0] if isinstance(choices, list) and choices else None
            message = first_choice.get("message") if isinstance(first_choice, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise ValueError("response content must be a string")
            usage = payload.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            return LlmReply(
                content=content,
                model=payload.get("model", self.model),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = is_retryable_status(status_code)
            raise DeepSeekClientError(
                "DeepSeek request failed",
                retryable=retryable,
                status_code=status_code,
                retry_after_seconds=_parse_retry_after(exc.response.headers.get("Retry-After")),
            ) from exc
        except httpx.TransportError as exc:
            raise DeepSeekClientError("DeepSeek request failed", retryable=True) from exc
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            # Preserve the HTTP status so the API can distinguish a malformed 200 body
            # from a transport failure after retries are exhausted.
            raise DeepSeekClientError(
                "DeepSeek returned an invalid response",
                retryable=True,
                status_code=response.status_code,
            ) from exc
