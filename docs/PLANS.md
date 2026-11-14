# Plans

> This file is the routing index for planning artifacts. Active work lives in `docs/exec-plans/active/`; finished work in `docs/exec-plans/completed/`.

## Roadmap

| Stage | Content | State |
|---|---|---|
| M0 | FastAPI skeleton, config, unified response/exception, request ID, pytest suite | done |
| M1 | Story-planning PoC — schema, validator, retry loop, preview API, eval set | code complete · 20/20 structure eval · **gate not passed** |
| M2 | Domain model, SQL, persistence | not started |
| M3+ | Player choice executor, prose generation, frontend | not started |

## Current gate

M1 passes only when **all** hold (see `docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md`):

1. Structure, business rules, error handling, observability implemented and proven.
2. Fixed 20-case real-model eval ≥ 16/20. (Currently 20/20.)
3. Owner completes code reading, hands-on modification, spoken defense.
4. No DB / frontend / RAG / multi-agent leaked into M1.

**Blocking now:** item 3. Tracked as `sc-m1-03` in `docs/harness/feature_list.json`.

## Active plans

- `docs/exec-plans/active/` — see index there.

## Historical (design/implementation) plans

- `docs/plans/2026-10-26-scenechoice-design.md`
- `docs/plans/2026-10-26-scenechoice-m0-implementation.md`
- `docs/plans/2026-11-05-scenechoice-m1-story-planning-design.md` (M1 baseline)
- `docs/plans/2026-11-06-scenechoice-competitor-capability-adoption.md`
- `docs/plans/2026-11-06-scenechoice-m1-implementation.md`
- `docs/plans/2026-11-07-scenechoice-m1-test-improvement-plan.md`

## Process

- One active feature at a time; status lives in `docs/harness/feature_list.json`.
- A plan moves from `active/` to `completed/` only when its feature is `passing` with evidence.
- Known gaps and deferred work are tracked in `docs/exec-plans/tech-debt-tracker.md`, not in chat.
