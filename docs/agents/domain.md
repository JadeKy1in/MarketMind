# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** — system-wide architectural decisions. In multi-context repos, also check `<context>/docs/adr/` for context-scoped decisions.
- If `CONTEXT-MAP.md` is missing, fall back to `CONTEXT.md` at the repo root.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## Adding a new context

1. Create `CONTEXT.md` in the project's root (e.g. `projects/new-project/CONTEXT.md`)
2. Create `docs/adr/` in the project's directory if it has its own architecture decisions
3. Add the project to `CONTEXT-MAP.md` at the repo root

## File structure (multi-context)

```
/
├── CONTEXT-MAP.md                     ← maps context names to paths
├── docs/adr/                          ← system-wide decisions
└── projects/
    ├── marketmind/                    ← active context
    │   ├── CONTEXT.md
    │   └── docs/adr/
    └── <future-project>/              ← add when needed
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
