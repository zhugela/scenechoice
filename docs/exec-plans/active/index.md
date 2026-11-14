# Active Exec Plans

> One active plan per in-progress feature. When a feature reaches `passing` (with evidence in `docs/harness/feature_list.json`), move its plan to `../completed/`.

## Currently active

None. M1 implementation and structural eval are done; the open item is owner learning acceptance (`sc-m1-03`), which is a personal verification task, not a build plan. M2 is blocked until the M1 gate passes.

## Template for a new active plan

Create `YYYY-MM-DD-<feature-id>.md` with:

- Goal (one sentence) and which `feature_list.json` id it satisfies.
- Scope: files/layers touched; explicit non-goals.
- Steps (small, verifiable).
- Verification: exact commands and the pass condition.
- Risks / rollback.
