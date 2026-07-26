# AGENTS.md

## Purpose

Jacquard is the agent-native programming environment, revision store, and MCP
server for Weave. The central object is a versioned program tree. Textual
`.weave` source is a deterministic view, not the primary editing surface.

## Architectural rules

1. **Never publish invalid program state.** A failed single edit, batch, or
   compiler-gated merge must not advance a branch head or leave partial audit
   rows.
2. **Published revisions are immutable.** A correction creates a new revision.
3. **Use stable semantic IDs.** Do not target source lines or formatting.
4. **Use the smallest coherent write unit.** Use one-node tools while exploring
   or repairing. A known local structure may use a bounded flat transaction of
   ordinary node operations. Never require a nested replacement AST.
5. **Keep batches bounded and auditable.** Every sub-operation must retain an
   ordered audit row, while the complete batch publishes as one revision or
   rolls back.
6. **Use optimistic concurrency for prepared edits.** Pass the expected base
   revision when a batch was planned from a specific branch head.
7. **Larger reads are acceptable.** Inspection may return a local subtree when it
   helps an agent understand context.
8. **Do not duplicate the Weave grammar.** `weavec` is authoritative. Grammar
   help is derived from its source corpus and completed programs are validated
   by its frontend.
9. **Merge structurally, analyze impact, validate before publication.**
   Non-overlapping node changes may merge automatically; incompatible changes
   must produce a clear conflict. Independent agents should preview the merge,
   identify affected named targets and uncovered changed documents, validate the
   relevant exact candidate targets, and publish with the reviewed gates.
10. **Context is versioned.** Interfaces, contracts, invariants, and design
    documents used by an agent must be reproducible from its base revision.
11. **Rendering is deterministic.** Identical database state and renderer version
    must produce byte-identical canonical source.
12. **SQLite is the prototype truth store.** Avoid adding a distributed database
    until measurements require it.

## Node identity

- New lists and atoms receive stable `n_*` IDs.
- Editing an atom or moving a node preserves its ID.
- Copying or creating a node gives it a new ID.
- Batch aliases are temporary names for stable IDs created in that transaction.
- Annotated source may display IDs, but canonical program meaning does not depend
  on them.
- Merge, diff, preview, impact, and MCP mutations target IDs, never line numbers.

## Structural writes

Single-node tools are the default for uncertain work. They create or change one
form, atom, edge, or location and publish one revision per successful call.

`node_apply_batch` is allowed for one coherent known structure. It must remain:

- a flat ordered list of existing structural operation kinds;
- bounded to a documented maximum;
- limited to one document and one pinned branch head;
- structurally validated before publication;
- one immutable revision with ordered per-operation audit rows;
- fully rolled back on any operation or stale-head failure.

Do not turn the batch tool into source replacement, a nested AST upload, an
unbounded request, or a way to bypass validation.

## Merge preview, impact, validation, and publication

`branch_merge_preview` is read-only. Its deterministic token must bind the
project, merge direction, common ancestor, target head, and source head. A clean
preview may report compact consequences but must never publish a snapshot or
advance a branch. A conflict preview must return exact conflict paths without
throwing away the reviewed head identities.

`branch_merge_impact` must compare the current target state with the prospective
merged state. It reports only consequences introduced by merging the source into
that target, not edits already present on the target branch. It must classify
added, removed, modified, and source-affected named targets deterministically and
paginate public target entries.

Target coverage must be computed from target definitions that survive in the
candidate. A removed target cannot hide a changed source document from
`uncovered_changed_documents`. Uncovered documents are explicit review signals:
they are not automatically invalid, but no candidate named target proves them.

`branch_merge_validate` must operate on the exact clean in-memory candidate. It
must resolve the named target and ordered sources from that candidate, invoke the
authoritative `weavec --frontend`, return bounded deterministic evidence, and
create no revision or retained build artifact. Never fabricate a temporary
revision merely to reuse revision-based validation APIs.

A validation response is evidence, not a bearer token. When `branch_merge`
receives `validation_target`, it must repeat validation and use that candidate's
preview ID for publication. Compiler unavailability, compiler rejection, merge
conflict, or stale preview state must leave the target branch unchanged.

Both reviewed branch heads must be rechecked inside the same SQLite write
transaction that publishes the merge. Any mismatch must return
`STALE_MERGE_PREVIEW` and leave the target branch and audit tables unchanged.
Direct merges without preview or validation remain supported, but they must still
capture and atomically recheck both current heads.

## Grammar and validation

The generic S-expression layer validates tree integrity:

- valid node shape;
- unique IDs;
- ordered children;
- legal atom values;
- no move cycles.

Do not add a second handwritten copy of the surface grammar. The MCP
`grammar_help` index reads `weavec/test/correctness/surface`. The
`program_validate`, `build_target_validate`, and `branch_merge_validate` tools
render canonical source and invoke `weavec --frontend`.

A later machine-readable grammar registry in `weavec` should replace corpus
inference without changing the public MCP API.

## Code layout

- `src/weave_frontend/service.py`: grammar-neutral revision and merge mechanics.
- `src/weave_frontend/sexpr.py`: generic S-expression nodes and rendering.
- `src/weave_frontend/sexpr_service.py`: single-node structural operations.
- `src/weave_frontend/batch_edit.py`: bounded transactional structural edits.
- `src/weave_frontend/revision_diff.py`: bounded stable-node revision diffs.
- `src/weave_frontend/merge_preview.py`: deterministic two-phase merge previews.
- `src/weave_frontend/merge_impact.py`: named-target and coverage impact analysis.
- `src/weave_frontend/merge_validation.py`: exact-candidate compiler validation.
- `src/weave_frontend/grammar_help.py`: guidance derived from compiler examples.
- `src/weave_frontend/weavec.py`: authoritative frontend validation adapter.
- `src/weave_frontend/compiler_*.py`: native compiler and artifact boundary.
- `src/weave_frontend/mcp_server.py`: base MCP tools.
- `src/weave_frontend/mcp_build.py`: production MCP entry point and extensions.
- `docs/architecture.md`: broad design and roadmap.
- `docs/mcp.md`: MCP workflow and public tool contract.
- `docs/edit-transactions.md`: bounded batch request and publication contract.
- `docs/merge-preview.md`: preview identity and atomic merge publication.
- `docs/merge-impact.md`: affected targets and uncovered candidate documents.
- `docs/merge-validation.md`: exact-candidate validation and compiler gate.
- `tests/`: executable specifications and real-MCP qualifications.

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

A passing structural merge is not enough. Review its affected target graph and
uncovered documents, then validate the exact candidate through the relevant named
targets before publication. After publication, preserve unique node IDs and run
any native build or execution checks required by the task.
