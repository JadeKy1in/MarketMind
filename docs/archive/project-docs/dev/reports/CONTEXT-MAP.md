# Context Map

Multi-context repo — each context has its own `CONTEXT.md` and optionally `docs/adr/`.

| Context | Path | Status |
|---------|------|--------|
| marketmind | `projects/marketmind/` | active |

## Adding a context

1. Create `CONTEXT.md` in the project directory
2. Create `projects/<name>/docs/adr/` if the project has its own architecture decisions
3. Add a row to the table above

Engineering skills (`diagnose`, `tdd`, `improve-codebase-architecture`) read this file to discover where domain documentation lives.
