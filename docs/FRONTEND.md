# Frontend

> **Status: not applicable in M1.** There is no frontend yet. M1 is a backend-only PoC (see `README.md` / `docs/PLANS.md`).

## When this applies

- Frontend work starts at **M6**, after persistence (M2) and the player loop exist.
- Until then, do not add UI code, a JS toolchain, or frontend dependencies.

## When it does apply, this file must answer

- Framework and version, rendering model (SPA / SSR), routing.
- State management and where server truth lives (the backend owns game state; the UI only reflects it).
- Design tokens / component system and accessibility baseline (WCAG 2.1 AA).
- How to verify UI changes in a real browser (screenshot + interaction evidence), not just type-check.

## Placeholder policy

Do not pre-build a frontend "to save time". Create the stack only when the milestone that needs it begins, and record the decision here first.
