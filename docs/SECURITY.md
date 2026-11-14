# Security & Privacy

> M1 scope: an unauthenticated preview endpoint with a single third-party model dependency.

## Secrets

- `SCENECHOICE_DEEPSEEK_API_KEY` is a `SecretStr`, loaded from environment / `.env`.
- `.env` and `.env.*.local` are git-ignored; only `.env.example` (empty values) is committed.
- Keys are never logged, echoed in errors, or returned in responses.
- `.env` contents and credentials must never be pasted into prompts or public files.

## What must not appear in logs

- API keys / credentials.
- The user's full inspiration text (error logs record the failure type and validation issues, not the raw idea).
- Raw model completions beyond the truncated repair excerpt already bounded by the prompt builder.

## Untrusted input

- The model response is treated as untrusted: parsed and validated (schema + business rules) before use.
- Request bodies are validated by Pydantic; failures return a uniform 422 envelope, not a stack trace.
- External input must not be interpolated into prompts in a way that lets it override system constraints (keep user text in the user turn, not the system message).

## Error surface

Errors are mapped to explicit codes so configuration problems are not disguised as outages:

| Condition | HTTP | code |
|---|---|---|
| Request/blueprint failure | 422 | 42201 |
| Model credentials rejected (401/403) | 503 | 50302 |
| Model temporarily unavailable | 502 | 50201 |
| Model not configured | 503 | 50301 |

## Test isolation

`tests/conftest.py` clears `SCENECHOICE_*` env, clears the settings cache, runs in a temp cwd (so a developer's `.env` cannot leak in), and blocks non-loopback sockets. Offline tests must never hit the real provider.

## Not yet / out of scope for M1

- Authentication / authorization, rate limiting, request size limits at the edge.
- Audit logging and PII retention policy (needed once stories are persisted in M2).
