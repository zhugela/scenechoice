# SceneChoice M1 Story Planning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a tested DeepSeek-powered endpoint that converts one sentence into a valid, executable 3- or 5-episode interactive-story blueprint.

**Architecture:** Pydantic owns field-level structure and ranges; a pure `BlueprintValidator` owns cross-field story rules. `StoryPlanner` orchestrates prompt construction, the injected DeepSeek-compatible client, JSON parsing, validation, and at most two repair attempts. The FastAPI endpoint returns a preview only and performs no persistence.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, DeepSeek OpenAI-compatible API, pytest.

---

### Task 1: Define the blueprint contract

**Files:**
- Create: `scenechoice/app/schemas/story_blueprint.py`
- Create: `scenechoice/tests/test_story_blueprint.py`

1. Write tests for a valid three-episode blueprint and invalid counts/ranges.
2. Run `pytest tests/test_story_blueprint.py -q` and confirm failure because models do not exist.
3. Implement constrained Pydantic models for characters, metrics, choices, episodes, ending conditions, endings, and the root blueprint.
4. Run the focused tests and confirm they pass.

### Task 2: Add deterministic business validation

**Files:**
- Create: `scenechoice/app/services/__init__.py`
- Create: `scenechoice/app/services/blueprint_validator.py`
- Create: `scenechoice/tests/test_blueprint_validator.py`

1. Write failing tests for duplicate IDs, broken references, episode numbering, indistinguishable choices, cliffhanger/resolution rules, ending categories, reachability, and ending priority.
2. Implement a pure validator returning structured issues rather than throwing on the first issue.
3. Enumerate the two metric ranges to prove every ending condition has at least one reachable state.
4. Run focused tests.

### Task 3: Implement DeepSeek transport and planning retries

**Files:**
- Modify: `scenechoice/app/config.py`
- Modify: `scenechoice/.env.example`
- Create: `scenechoice/app/clients/__init__.py`
- Create: `scenechoice/app/clients/deepseek.py`
- Create: `scenechoice/app/prompts/__init__.py`
- Create: `scenechoice/app/prompts/story_planning.py`
- Create: `scenechoice/app/services/story_planner.py`
- Create: `scenechoice/tests/test_deepseek_client.py`
- Create: `scenechoice/tests/test_story_planner.py`

1. Write fake-client tests covering first-pass success, invalid JSON repaired on the second call, three failures, and usage aggregation.
2. Add timeout/model settings without exposing secrets.
3. Implement an async httpx client for DeepSeek's OpenAI-compatible chat-completions endpoint.
4. Build initial/repair prompts from the JSON Schema and structured validation issues.
5. Implement three total attempts and a sanitized `StoryPlanningError`.
6. Run focused tests.

### Task 4: Expose the M1 preview API

**Files:**
- Modify: `scenechoice/app/errors.py`
- Modify: `scenechoice/app/main.py`
- Create: `scenechoice/app/api/__init__.py`
- Create: `scenechoice/app/api/story_plans.py`
- Create: `scenechoice/app/dependencies.py`
- Create: `scenechoice/tests/test_story_plans_api.py`

1. Write endpoint tests with dependency overrides so no test calls a live model.
2. Add `POST /api/story-plans/preview` accepting inspiration and episode count.
3. Map missing API configuration and planning exhaustion to safe application errors.
4. Return blueprint plus attempts, model, token counts, and duration.
5. Run API and regression tests.

### Task 5: Add the fixed 20-topic evaluation gate

**Files:**
- Create: `scenechoice/evals/story_planning_cases.json`
- Create: `scenechoice/evals/run_story_planning_eval.py`
- Create: `scenechoice/tests/test_evaluation_cases.py`
- Modify: `scenechoice/README.md`

1. Add 20 synthetic, privacy-safe prompts spanning livestreaming, gaming, suspense, workplace, family, emotion, campus, and science fiction.
2. Test that IDs are unique, there are exactly 20 cases, and all required genres are covered.
3. Implement a live runner that writes a timestamped JSON report and exits successfully only at 16/20 or better.
4. Document configuration, API use, tests, and the evaluation command.

### Task 6: Verify and publish

1. Run the full test suite under the working Python 3.12 environment.
2. Check whether a DeepSeek key is configured without printing it; if present, run the live 20-case gate, otherwise record it as pending rather than fabricating results.
3. Inspect `git diff --check` and scan changed public files for secrets or internal company data.
4. Commit the M1 implementation and push the current branch.
