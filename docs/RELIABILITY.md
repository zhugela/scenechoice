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

## SQLite concurrency assumptions (SQLite 并发假设)

- WAL lets readers and the writer proceed without blocking each other, but **writes are still single-writer**. Two processes writing at the same time queue for up to `SQLITE_BUSY_TIMEOUT_MS` (5s, `app/db.py`); after that the loser gets `database is locked`. `busy_timeout` is the lock-wait deadline, not SQLAlchemy's connect timeout.
- WAL adds `-wal` and `-shm` files next to the database. Both are git-ignored (`.gitignore`: `*.db-wal`, `*.db-shm`). Any backup or copy of the database must include them, or run `PRAGMA wal_checkpoint(TRUNCATE)` first.
- 时间戳契约：库里存 UTC（`app/models/base.py:utcnow`），读回时由 `as_utc()` 补回 UTC 标签，
  对外一律输出**带偏移**的 ISO-8601 —— `2026-11-20T09:12:33.123456Z` 或 `+00:00` 都算合法，
  唯一不可接受的是没有偏移的裸串（客户端会按自己的本地时区解释）。
- This section matters at M3: before moving to multiple worker processes or containers, re-read it. WAL does not make SQLite a multi-writer store; a single writer (or serialized writes) remains the safe assumption.

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
