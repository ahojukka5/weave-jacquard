# AGENTS.md

## Purpose

This repository prototypes an agent-native frontend, program store, and MCP
server for Weave. The central object is a versioned program tree. Textual
`.weave` source is a deterministic view, not the primary editing surface.

## Architectural rules

1. **Never edit program state without validation.** A failed operation must be
   atomic and must not advance a branch head.
2. **Published revisions are immutable.** A correction creates a new revision.
3. **Use stable semantic IDs.** Do not target source lines or formatting.
4. **Keep agent writes atomic.** The normal MCP write path creates or changes one
   form, atom, edge, or location per call. Do not replace this with a required
   large nested JSON payload.
5. **Larger reads are acceptable.** Inspection may return a local subtree when it
   helps an agent understand context.
6. **Do not duplicate the Weave grammar.** `weavec2` is authoritative. Grammar
   help is derived from its source corpus and completed programs are validated
   by its frontend.
7. **Merge structurally, validate semantically.** Non-overlapping node changes
   may merge automatically; incompatible changes must produce a clear conflict.
8. **Context is versioned.** Interfaces, contracts, invariants, and design
   documents used by an agent must be reproducible from its base revision.
9. **Rendering is deterministic.** Identical database state and renderer version
   must produce byte-identical canonical source.
10. **SQLite is the prototype truth store.** Avoid adding a distributed database
    until measurements require it.

## Node identity

- New lists and atoms receive stable `n_*` IDs.
- Editing an atom or moving a node preserves its ID.
- Copying or creating a node gives it a new ID.
- Annotated source may display IDs, but canonical program meaning does not depend
  on them.
- Merge and MCP mutations target IDs, never line numbers.

## Grammar and validation

The generic S-expression layer validates tree integrity after every mutation:

- valid node shape;
- unique IDs;
- ordered children;
- legal atom values;
- no move cycles.

Do not add a second handwritten copy of the surface grammar. The MCP
`grammar_help` index reads `weavec2/test/correctness/surface`. The
`program_validate` tool renders canonical source and invokes
`weavec2 --frontend`.

A later machine-readable grammar registry in weavec2 should replace corpus
inference without changing the public MCP API.

## Code layout

- `src/weave_frontend/grammar.py`: original typed prototype grammar.
- `src/weave_frontend/service.py`: original typed workspace and revision model.
- `src/weave_frontend/sexpr.py`: generic S-expression nodes, parser, and renderer.
- `src/weave_frontend/sexpr_service.py`: atomic node operations and node merge.
- `src/weave_frontend/grammar_help.py`: help derived from weavec2 examples.
- `src/weave_frontend/weavec2.py`: authoritative frontend validation adapter.
- `src/weave_frontend/mcp_server.py`: MCP tools and server entry point.
- `docs/architecture.md`: broad design and roadmap.
- `docs/mcp.md`: MCP workflow and tool contract.
- `tests/`: executable specifications.

## Change protocol

Before changing behavior:

1. Read `docs/architecture.md`, `docs/mcp.md`, and affected tests.
2. State the invariant being changed or preserved.
3. Add or update tests with the behavior change.
4. Keep database migrations explicit and backwards-aware.
5. Run:

```bash
python -m compileall -q src tests
ruff check .
pytest
```

## Merge expectations

A passing text merge is not enough. After merge, preserve unique node IDs, run
structural validation, invoke weavec2 for complete programs, and execute affected
tests.
