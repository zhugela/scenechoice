# SceneChoice M0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal, testable FastAPI foundation for SceneChoice with configuration, consistent errors, request tracing, and a health endpoint.

**Architecture:** Keep the application factory in `app/main.py`, cross-cutting configuration and errors under `app/core`, and HTTP routes under `app/api`. Build each capability test-first and avoid database, LLM, RAG, and workflow dependencies during M0.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pydantic-settings, pytest, FastAPI TestClient, structlog.

---

### Task 1: Minimal FastAPI application and health endpoint

**Files:**
- Create: `scenechoice/app/__init__.py`
- Create: `scenechoice/app/main.py`
- Create: `scenechoice/tests/__init__.py`
- Create: `scenechoice/tests/test_health.py`
- Create: `scenechoice/requirements.txt`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

**Step 2: Run test to verify it fails**

Run from `scenechoice`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_health.py -v
```

Expected: FAIL during import because `app.main` does not exist yet.

**Step 3: Write the minimal implementation**

```python
from fastapi import FastAPI

app = FastAPI(title="SceneChoice")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Step 4: Run the test again**

Expected: one test passes.

**Step 5: Commit**

```powershell
git add scenechoice/app scenechoice/tests scenechoice/requirements.txt
git commit -m "feat: add SceneChoice health endpoint"
```

### Task 2: Typed environment configuration

**Files:**
- Create: `scenechoice/app/core/__init__.py`
- Create: `scenechoice/app/core/config.py`
- Create: `scenechoice/tests/test_config.py`
- Create: `scenechoice/.env.example`
- Create: `scenechoice/.gitignore`

**Steps:**

1. Write tests that default `APP_NAME` to `SceneChoice` and allow environment overrides.
2. Run tests and confirm the configuration module is missing.
3. Implement a cached `Settings` object with `pydantic-settings`.
4. Run configuration and health tests.
5. Verify `.env` is ignored and `.env.example` contains no real secret.
6. Commit as `feat: add typed application settings`.

### Task 3: Unified API response and exception handling

**Files:**
- Create: `scenechoice/app/schemas/__init__.py`
- Create: `scenechoice/app/schemas/response.py`
- Create: `scenechoice/app/core/exceptions.py`
- Modify: `scenechoice/app/main.py`
- Modify: `scenechoice/tests/test_health.py`
- Create: `scenechoice/tests/test_errors.py`

**Steps:**

1. Define the expected success and error JSON in tests.
2. Verify tests fail before implementation.
3. Implement generic `ApiResponse`, an application exception, and exception handlers that preserve real HTTP status codes.
4. Verify `/health`, validation errors, and application errors.
5. Commit as `feat: add consistent API responses`.

### Task 4: Request ID and structured request logging

**Files:**
- Create: `scenechoice/app/core/logging.py`
- Create: `scenechoice/app/core/middleware.py`
- Modify: `scenechoice/app/main.py`
- Create: `scenechoice/tests/test_request_context.py`

**Steps:**

1. Test that every response has an `X-Request-ID` header.
2. Test that a caller-provided request ID is preserved.
3. Implement middleware that records method, path, status, request ID, and elapsed milliseconds.
4. Run the complete test suite.
5. Commit as `feat: add request tracing and logging`.

### Task 5: M0 verification and usage documentation

**Files:**
- Modify: `scenechoice/README.md`
- Create: `scenechoice/pytest.ini`

**Steps:**

1. Document environment setup, test, start, and health-check commands.
2. Run `python -m pytest -q` and confirm all tests pass.
3. Start Uvicorn and verify `GET /health` returns the documented response.
4. Check `git status` for secrets, caches, and unrelated files.
5. Commit as `docs: document SceneChoice M0 setup`.

