# AGENTS.md

## Purpose

This repository prototypes an agent-native frontend and program store for
Weave. The central object is a typed, versioned program tree. Textual `.weave`
source is a deterministic import/export view, not the authoritative editing
surface.

## Architectural rules

1. **Never edit program state without validation.** A failed operation must be
   atomic and must not advance a branch head.
2. **Published revisions are immutable.** A correction creates a new revision.
3. **Use stable semantic IDs.** Do not target source lines or formatting.
4. **Keep agent operations small and general.** Prefer inspect/insert/replace/
   delete/validate over a large collection of special-case tools.
5. **Incomplete work uses explicit holes.** Do not represent malformed partial
   syntax as a draft.
6. **Merge structurally, validate semantically.** Non-overlapping symbols may
   merge automatically; incompatible changes must produce a clear conflict.
7. **Context is versioned.** Interfaces, contracts, invariants, and design
   documents used by an agent must be reproducible from its base revision.
8. **Rendering is deterministic.** Identical database state and renderer version
   must produce byte-identical source output.
9. **SQLite is the prototype truth store.** Avoid adding a server or distributed
   database until concurrency measurements require it.
10. **Do not couple this prototype prematurely to current compiler internals.**
    The long-term boundary is a canonical semantic IR and snapshot format.

## Code layout

- `src/weave_frontend/grammar.py`: grammar, structural checks, type checking.
- `src/weave_frontend/database.py`: SQLite schema and transaction helpers.
- `src/weave_frontend/service.py`: agent-facing workspace operations, history,
  branches, context, and merge.
- `src/weave_frontend/renderer.py`: deterministic surface-Weave view.
- `docs/architecture.md`: design and roadmap.
- `tests/`: executable specifications for required behavior.

## Change protocol

Before changing behavior:

1. Read `docs/architecture.md` and the tests covering the affected subsystem.
2. State the invariant being changed or preserved.
3. Add or update a test first when fixing a bug or changing semantics.
4. Keep database migrations explicit and backwards-aware.
5. Run:

```bash
pytest
ruff check .
```

## Merge expectations

Changes are safe to auto-merge only when their semantic targets do not overlap
or the three-way merge proves they are equivalent. Passing text merge is not
enough. After merge, run structural validation, symbol resolution, type checks,
and affected tests.

## Scope of the prototype

The current grammar is intentionally small. Add new language constructs only
with:

- a precise AST shape;
- immediate structural validation;
- deterministic rendering;
- semantic/type rules;
- merge behavior;
- unit tests.
