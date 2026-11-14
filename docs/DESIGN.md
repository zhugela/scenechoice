# Design

> Rationale and decisions. For structure see `ARCHITECTURE.md`; for retry/cost see `RELIABILITY.md`.

## Product decision

M1 verifies one risky claim: DeepSeek can turn one line of inspiration into an executable, finishable interactive-drama blueprint, reliably enough to build on.

- Generate the full 3- or 5-episode blueprint at creation time (not episode-by-episode).
- Each episode offers exactly two choices.
- Two core states, named by the model per story, always 0–100.
- At least three reachable endings.
- **Rules decide facts and consequences; the AI only narrates.**
- Model output is valid only after backend validation.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Plan-as-you-play (generate next episode after each choice) | drifts, may never converge, cannot prove "guaranteed ending" |
| Pre-generate all branch prose | exponential branches, high cost, wasted content |
| Let the LLM write game state directly | non-reproducible, untestable, unfair endings (see `docs/design-docs/core-beliefs.md`) |

## Key decisions

| Decision | Why |
|---|---|
| Pydantic schema + explicit `BlueprintValidator` | JSON Schema cannot express cross-field story logic (unreachable endings, duplicate ids, choice divergence) |
| Bounded repair: 3 total attempts | one bad generation should not kill a session; infinite retry hides systemic prompt bugs |
| Structured repair feedback to the model | re-generating with the concrete validation errors beats a blind retry |
| `CompletionClient` Protocol + DI | planner depends on "something that completes messages", so tests use fakes and the model can be swapped |
| Fixed 20-case eval set with 16/20 gate | regressions become measurable, not anecdotal |
| No DB in M1 | keeps the feedback loop short; persistence is an M2 concern |

## Why not let the LLM mutate state

If "reputation" is 50 and a choice is `+12`, Python must produce 62. If the model decides, it may write 80 "for the story", forget it next turn, and make the same choice non-reproducible. So:

> Python decides facts and numbers; the AI makes already-decided facts read well.

## Open design question

Rule 10 ("no undefined characters or key items needed to finish") is only partly enforced: new character references are checked, but there is no structured `items` registry, so key-item dependencies rely on prompt + human review. Do not silently expand the schema; revisit only if real evals fail on it often.
