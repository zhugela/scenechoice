# Generated Artifacts

> Machine-generated snapshots committed on purpose so agents don't rely on chat or memory for structural facts.

| Artifact | Source | Status |
|---|---|---|
| `db-schema.md` | DB migrations / models | Not applicable — no database in M1 (M2 adds it) |

## Why commit generated files

A generated schema/route snapshot is a cheap, always-current reference for an agent: it removes a round of exploration and prevents stale assumptions. Regenerate (don't hand-edit) when the source changes.

## When `db-schema.md` appears

At M2, once SQL models/migrations exist, generate the schema here from the migration source and note the generation command in this file.
