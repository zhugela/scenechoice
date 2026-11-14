# Tech Debt Tracker

> Known gaps, deferred work, and structural debt. Keep this current so debt is visible, not rediscovered each session.

## Open

| # | Area | Debt | Impact | Trigger to pay |
|---|---|---|---|---|
| 1 | Validator rule 10 | No structured `items` registry; key-item dependencies rely on prompt + human review | Rule 10 only partly enforced | Pay if real evals fail on it often; do not silently expand the schema |
| 2 | Reachability | Rule 8 checks theoretical state-space reachability, not playable-path reachability | Passing tests can't rule out unreachable endings in real play | Needs the M3 player-loop simulator |
| 3 | Fixtures | Most tests reuse one 3-episode fixture; 5-episode path, dual-metric endings, boundary text under-covered | Shape-specific bugs may hide | Add fixtures before M2 data model work |
| 4 | Eval evidence | 20/20 report is local/ignored and predates the venv repair | Evidence not re-run post-repair | Re-run before declaring gate passed |
| 5 | Init network | `pip install` can be sandbox-blocked / silent-fail; init.sh relies on it | Onboarding friction | Add `--skip-install` or standardize on `uv` |

## Closed

- Root-dir leftover install junk (pip-*/pytest temp) — cleaned 2026-11-12.
