# Core Beliefs

> Non-negotiables. If a change violates one of these, stop and raise it, don't route around it.

1. **Do not trust the model.** Its output is untrusted input; schema + business validation gate everything.
2. **Rules decide facts, the AI narrates.** Numbers and consequences come from Python, reproducibly. The model may make them read well, never invent state.
3. **Fail loudly, bounded.** At most 3 attempts, then an explicit error. No infinite retry; no silent partial blueprint.
4. **Evidence over vibes.** A change is "done" only when a command was run and its result recorded — especially the 16/20 gate. "Should work" is not evidence.
5. **Never lower the gate to look complete.** Don't weaken tests or the stage threshold to make progress appear better.
6. **Python decides, code is understood.** Every module must be explainable by the owner; unread generated code is a liability, not an asset.
7. **Keep the loop short until the gate passes.** No DB / frontend / RAG / multi-agent before M1 passes.
8. **Small units, one at a time.** One invariant or rule per change, verified normal + failure path.
9. **The repo is the source of truth.** State lives in files (`harness/`), not chat history.
