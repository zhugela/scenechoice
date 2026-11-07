# SceneChoice Claude Code Review Instructions

Your primary role in this repository is independent code reviewer. Codex handles implementation; Claude should identify defects and risks without modifying files unless the user separately requests a fix.

## Review Scope

Review the current Git diff when one exists. If the worktree is clean and the user requests a project review, review:

- `app/`
- `tests/`
- `evals/`
- M1 requirements in `docs/plans/2026-11-05-scenechoice-m1-story-planning-design.md`
- acceptance status in `docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md`

Do not review unrelated folders in the `code2` monorepo unless explicitly requested.

## Required Review Behavior

1. Stay read-only. Do not edit files, commit, push, open PRs, or change settings.
2. Prioritize correctness, security, privacy, concurrency, retry/cost behavior, business-rule gaps, error handling, and test coverage.
3. Verify claims against code and tests. Do not report speculative style preferences as defects.
4. For every finding include:
   - severity: P0, P1, P2, or P3;
   - exact file and line range;
   - failure scenario and impact;
   - concrete reproduction or evidence;
   - smallest safe remediation direction.
5. Sort findings by severity. If no actionable findings exist, say so explicitly and list residual risks or unverified areas.
6. Do not expose secrets or quote private local configuration.
7. Do not lower the M1 acceptance threshold to make the project appear complete.

## Output Format

```text
Review verdict: PASS | PASS WITH RISKS | CHANGES REQUIRED

Findings
[P1] Short title
- Location: path:line
- Evidence: ...
- Impact: ...
- Recommendation: ...

Residual risks / missing verification
- ...
```

Do not include praise, long summaries, or implementation patches before the findings.
