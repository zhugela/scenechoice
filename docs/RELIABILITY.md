# Reliability

> Retry, timeout, cost and observability. Everything here maps to code in `app/clients/deepseek.py` and `app/services/story_planner.py`.

## Settings (env prefix `SCENECHOICE_`, validated at startup)

| Setting | Default | Bounds |
|---|---|---|
| `deepseek_timeout_seconds` | 30.0 | 0 < x ≤ 120 |
| `deepseek_max_tokens` | 4096 | 256–8192 |
| `story_planning_max_attempts` | 3 | 1–5 |
| `story_planning_retry_base_seconds` | 0.5 | 0–10 |
| `story_planning_retry_max_seconds` | 8.0 | 0–60 |

## Error classification (`DeepSeekClient`)

| Signal | Retryable? | Result |
|---|---|---|
| HTTP 408, 429, ≥500 | yes | `DeepSeekClientError(retryable=True)` |
| HTTP 401/403 | no | raised; API maps to `503` / code `50302` |
| `httpx.TransportError` (timeout, network) | yes | `DeepSeekClientError(retryable=True)` |
| Malformed payload (non-object, no content) | yes | `DeepSeekClientError(retryable=True)` |

`Retry-After` is parsed and honored when present (clamped to `retry_max_seconds`).

## Bounded repair loop (`StoryPlanner.plan`)

1. Call model. On retryable client error and attempts left → sleep backoff → retry. Non-retryable → raise immediately.
2. Parse JSON → `StoryBlueprint.model_validate_json`.
3. Run `BlueprintValidator` + episode-count check.
4. Pass → return `PlanningResult` (attempts, tokens, duration).
5. Fail → build `repair_messages(base, last_output, issues)`, retry.
6. After `max_attempts` → `StoryPlanningError` (attempts, issues). Never persists or returns a broken blueprint.

Backoff: `Retry-After` if given, else `base * 2^(attempt-1)`, capped at `retry_max_seconds`.

## Cost controls

- Hard cap per call: `max_tokens` (default 4096).
- Hard cap per request: `max_attempts` (default 3) bounds worst-case token spend.
- Repair replays at most ~12k chars of the previous output plus up to 30 issues.
- `planning` logs aggregate prompt/completion tokens; the 20-case eval reports totals.

## Observability

Logs include `request_id`, `model`, `attempts` (or `attempt`), `duration_ms`, token counts, and failure type. They must **not** include the API key or the user's full inspiration (see `SECURITY.md`).

## Verification status

- Covered by unit tests: 401/429/timeout/5xx classification, invalid JSON, three-attempt exhaustion, log privacy, request-id propagation.
- Not yet verified against the real provider: exact `usage` field names, `Retry-After` behavior, and `response_format=json_object` compliance — confirm on the next real run.
