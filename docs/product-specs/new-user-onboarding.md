# New User Onboarding

> **Status: not applicable in M1.** There is no user-facing UI yet, so there is no onboarding flow to specify.

## When this applies

Onboarding becomes relevant at **M6** (frontend), once a player can actually open the product.

## What it must eventually cover

- First-run experience: how a user gives one line of inspiration and picks 3 or 5 episodes.
- What the user sees while the blueprint is generated (bounded retries take a few seconds up to ~tens of seconds).
- Error states: model unavailable, credentials rejected, request invalid — mapped to plain-language messages (see `../SECURITY.md` error table).
- Time-to-first-fun: the 5–10 minute first play target from `../PRODUCT_SENSE.md`.

## Placeholder policy

Do not design onboarding before the backend and player loop exist. Record the decision to defer here rather than inventing flows that will change.
