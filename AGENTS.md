# SceneChoice Agent Context

## Mission

SceneChoice is both a product and a learning project. The long-term goal is to help the owner genuinely master Python, FastAPI, AI Agent engineering, testing, deployment, and project explanation well enough to pursue an approximately 15K RMB AI application developer role in Shenzhen.

Do not optimize only for writing more code. Every completed module must eventually be understood, modified, explained, and defended by the owner.

## Current Stage

- M0 engineering foundation: complete.
- M1 story-planning PoC implementation: complete.
- M1 stage gate: not passed.
- Do not begin M2 until both conditions are met:
  1. a real DeepSeek 20-case evaluation reaches at least 16 structural passes;
  2. the owner completes the personal learning checks in `docs/learning/scenechoice-m1-learning-review.md`.

The authoritative audit is `docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md`.

## Session Startup & Handoff (harness)

Two state files are mandatory. They are the only cross-session truth; chat history is not.

Before touching code:

1. Run `./init.sh`. If baseline verification fails, repair the environment first instead of stacking new work.
2. Read `progress.md` (current verified state, last session, next best action).
3. Read `feature_list.json` and pick exactly one `not_started` or `in_progress` feature. Never work on two at once.

Before ending a session:

1. Update `progress.md`: what was verified, what broke, next best action.
2. Update the feature status in `feature_list.json`. `passing` requires evidence recorded in its `evidence` field.
3. Never weaken tests, or the M1 stage gate, to make progress look better.

## Learning-Coach Rules

When asked to teach this project:

1. Explain one small concept at a time in plain Chinese and prefer everyday analogies.
2. Ask the learner to predict output or behavior before revealing the answer.
3. Base lessons on the actual repository code, not generic tutorials.
4. Never complete the learner's reserved hands-on tasks for them. The duplicate-`character_ids` validator rule was already implemented by the owner in commit `a6b08cf`; treat it as completed learning evidence, not as a task to redo. Pick the next hands-on task from `docs/learning/scenechoice-m1-learning-review.md`.
5. Record what the learner can explain, what remains uncertain, and the next smallest exercise.
6. Distinguish “code exists” from “learner has mastered it.”

## AI-Assisted Development Workflow

Core principle: the biggest risk is not that AI writes incorrect code, but that code the owner does not understand remains in the project. Optimize for reading and verification, not generation speed.

Before each implementation unit:

1. State the input, output, boundary conditions, and acceptance criteria. Do not implement until these are clear.
2. Implement only one small unit at a time, sized so the owner can read it immediately.
3. After generation, pause for the owner to explain in one sentence what it does, identify the key lines, and ask about unfamiliar syntax or libraries.
4. Verify both a normal path and at least one relevant failure path. “Should work” is not evidence.
5. Record one concise “why” for non-obvious design choices in a comment, test name, commit message, or learning note.

Do not continue stacking implementation units while the previous unit remains unread, unexplained, or unverified.

Recommended reading order:

1. `app/schemas/story_blueprint.py`
2. `app/services/blueprint_validator.py`
3. `app/services/story_planner.py`
4. `app/api/story_plans.py`
5. `app/clients/deepseek.py`

## Safety and Confidentiality

- Never expose API keys, `.env` contents, credentials, or local authentication data.
- Do not include private employer, mentor, or internal-company information in public files or external prompts.
- Do not change source code during a learning-only session unless the owner explicitly asks for implementation.
- Preserve the M1 scope: no database, frontend, RAG, or multi-agent expansion before the stage gate passes.

## Verification

From this directory, the standard test command is:

```powershell
python -m pytest -q
```

The repository also runs `.github/workflows/ci.yml` on GitHub (Python 3.12, `pytest -q`).
