# External References

Reference material (LLM-friendly dumps, external docs) kept in-repo so agents don't depend on live web access or memory.

| File | Covers | Status |
|---|---|---|
| `python-fastapi-llms.txt` | FastAPI / Pydantic usage we rely on | to add when a version-sensitive change lands |
| `uv-llms.txt` | `uv` usage for venv/install | **recommended next** — this repo's venv is uv-managed |
| `nixpacks-llms.txt` | Nixpacks build config | **not applicable** — not used for this project's deploy |

## Policy

- Add a reference only when it removes real ambiguity for a recurring task.
- Keep them small and versioned to what we actually use; don't bulk-import.
- Prefer official upstream docs; note the source URL and date in the file header.
