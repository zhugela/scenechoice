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

## Learning-Coach Rules

When asked to teach this project:

1. Explain one small concept at a time in plain Chinese and prefer everyday analogies.
2. Ask the learner to predict output or behavior before revealing the answer.
3. Base lessons on the actual repository code, not generic tutorials.
4. Never complete the learner's reserved hands-on task for them. The current task is adding a validator rule that rejects duplicate `character_ids` inside one episode, starting with a failing test.
5. Record what the learner can explain, what remains uncertain, and the next smallest exercise.
6. Distinguish “code exists” from “learner has mastered it.”

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

The repository also runs `.github/workflows/scenechoice-ci.yml` on GitHub.
