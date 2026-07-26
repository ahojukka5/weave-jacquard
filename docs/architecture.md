# Jacquard architecture

## 1. Thesis

A coding agent should not have to emit and maintain a complete source file.
Instead, it operates on a versioned program tree through a compact tool surface:

```text
DISCOVER → INSPECT → MUTATE → PREVIEW → VALIDATE CANDIDATE → MERGE → BUILD → TEST
```

Jacquard owns syntax-tree identity, immutable revisions, transactional safety,
canonical source materialization, build provenance, and reviewed branch
publication. The agent concentrates on local algorithmic decisions. The
authoritative language implementation and native compiler remains
[`weavec`](https://github.com/ahojukka5/weavec).

## 2. Program structure

An S-expression is an ordered rooted n-ary tree. The database stores immutable
snapshots and stable node IDs.

```text
workspace
└── project
    ├── program documents
    ├── named build targets
    ├── contracts and design context
    ├── branches
    ├── immutable revisions
    └── verified build artifacts
```

Surface Weave, WIR, LLVM IR, bitcode, objects, and native executables are
derivatives of a pinned program revision. A prospective merge candidate is a
validated in-memory state, not a temporary revision or persisted artifact.

## 3. Agent API

### Discovery and inspection

- `weave_help`
- `grammar_help`
- `program_list`
- `program_source_list`
- `program_render`
- `node_find`
- `node_inspect`
- `revision_diff_page`
- `branch_merge_preview`
- `branch_merge_validate`
- `context_get`
- `build_get`
- `build_diagnostics_page`

### Mutation

- `program_create`
- `program_import`
- `node_create_form`
- `node_add_atom`
- `node_set_atom`
- `node_move`
- `node_wrap`
- `node_delete`
- `node_apply_batch`
- `context_add`

### Verification, build, merge, and history

- `program_validate`
- `program_build`
- `build_target_set`
- `build_target_list`
- `build_target_get`
- `build_target_delete`
- `build_target_validate`
- `build_target_build`
- `branch_create`
- `branch_list`
- `branch_history`
- `branch_history_page`
- `revision_operations_page`
- `branch_activity_summary`
- `branch_merge`

The MCP server is a transport layer over the same workspace, merge-preview,
merge-validation, and compiler-bridge services used by the Python
implementation.

## 4. Structural write modes

Jacquard supports two complementary source-edit modes.

### Single-node edits

Use one-node tools while exploring, repairing, or making a decision that should
be inspected immediately. Each successful call publishes one immutable
revision.

### Bounded edit transactions

Use `node_apply_batch` after one coherent local structure is known. A batch is a
flat ordered list of 1–256 ordinary structural operations. It may use temporary
aliases for nodes created earlier in the same request.

A batch:

- pins one document at one branch head;
- optionally checks an expected revision;
- applies every operation in memory;
- validates the complete resulting tree once;
- writes one immutable snapshot;
- records every sub-operation as an ordered audit row;
- compare-and-set advances the branch;
- rolls back completely on any failure.

The batch interface must never become an unbounded nested AST replacement. See
[`edit-transactions.md`](edit-transactions.md).

## 5. Validation and incomplete programs

Every persisted write must preserve structural validity. A failed operation,
batch, or compiler-gated merge returns a structured error and does not advance
the branch head.

The generic S-expression layer guarantees:

- legal node shapes and atom values;
- stable, unique node IDs;
- ordered children;
- no move cycles;
- deterministic rendering.

A partially constructed form may be structurally valid but semantically
incomplete. Grammar help guides construction; `program_validate` performs the
normative completed-program check through:

```text
weavec --frontend output.wir input.weave
```

`build_target_validate` applies the same authority to one ordered source set
from an immutable revision. `branch_merge_validate` applies it to a named target
resolved from an exact clean in-memory merge candidate before publication.

Jacquard does not maintain a handwritten copy of the full surface grammar.
Until `weavec` exposes a machine-readable registry, grammar guidance is inferred
from its correctness corpus.

## 6. Persistence and publication

The prototype uses SQLite because it is embedded, transactional, portable, and
supports rich queries over revisions and context.

Core concepts include:

```text
projects
revisions
branches
module snapshots
operations
context documents
revision documents
```

Snapshots are compressed transparently and revisions are immutable. A branch is
a named pointer to one revision. The operation log explains how the snapshot was
produced.

Single-node publication uses one transaction per edit. Batched publication uses
one transaction for the complete operation list and a compare-and-set branch
update. Merge publication uses one transaction that rechecks both captured
branch heads, writes the structurally and optionally compiler-validated merged
snapshot, records both parents, and compare-and-set advances only the target
branch.

Candidate validation is deliberately outside persistence. It uses private
temporary files owned by the compiler adapter and retains only bounded response
evidence. No schema row is created for a preview or validation attempt.

All publication modes preserve the same revision DAG and audit model; no schema
migration is required.

A production implementation may later deduplicate immutable nodes or modules by
content hash, but measurements—not aesthetics—should drive that change.

## 7. Compiler and artifact boundary

Compilation resolves one explicit ordered source set from one immutable
revision:

```text
SQLite revision
→ canonical .weave sources and node maps
→ final weavec
→ validated manifest and diagnostics
→ verified content-derived artifact store
```

Prospective merge validation uses the narrower frontend boundary:

```text
in-memory clean merge candidate
→ named target + ordered canonical sources
→ weavec --frontend
→ bounded source/compiler/WIR hash evidence
```

The second path creates no revision, executable, build manifest, diagnostics
artifact, or retained WIR. It proves that the exact combined candidate is
accepted by the authoritative frontend before branch publication.

`weavec` owns surface lowering, WIR, LLVM generation, runtime selection, object
generation, linking, and native output. Jacquard owns revision pinning, source
order, canonical materialization, node maps, compiler protocol validation,
artifact hashing, cache identity, and atomic publication.

Build artifacts are admitted only when their paths, hashes, compiler manifest,
diagnostics protocol, source order, target, output, and requested build identity
all agree. Concurrent candidates are serialized per build ID; an existing
verified success wins.

## 8. History and backup

Revisions are immutable and form a DAG. A user-facing revert normally creates a
new revision so the revert itself remains reversible.

```text
R0 ── R1 ── R2
      ├── agent/foo: R3
      └── agent/bar: R4
```

Internal history is not a physical backup. Production operation also requires
consistent database backups, integrity checks, artifact retention, and orphan
cleanup.

## 9. Parallel agents, preview, validation, and merge

Every agent receives:

- a base revision;
- a private branch;
- an edit scope;
- pinned interfaces and context;
- tests and acceptance criteria.

Three-way merge compares a common base revision with both branch heads.

- one branch changed a node and the other did not: take the change;
- both produced identical content: take either;
- both changed the same identity differently: conflict;
- independent node changes: merge automatically.

`branch_merge_preview` performs that stable-ID merge without publishing. It
returns either exact conflict paths or a structurally validated prospective
merged root with compact per-document node consequences. Complete merged trees
are not sent over MCP.

The deterministic `weave-merge-preview-v1` identity binds:

```text
project
+ target and source branch names
+ common ancestor revision
+ target head revision
+ source head revision
```

`branch_merge_validate` reuses the exact clean candidate internally, resolves a
named build target and its ordered sources from that state, and invokes
`weavec --frontend`. Its `weave-merge-validation-v1` identity additionally binds
the merged root, target configuration, ordered source hashes, and compiler
binary hash. It stores no preview, revision, or build artifact.

Passing `preview_id` and `validation_target` to `branch_merge` forms a reviewed,
compiler-gated publication protocol:

1. recompute the current candidate;
2. reject a stale supplied preview;
3. repeat authoritative target validation;
4. reject unavailable or failed compiler validation;
5. use the validated candidate's preview ID;
6. check both heads inside the `BEGIN IMMEDIATE` publication transaction;
7. write the immutable two-parent merge revision.

A branch change before validation changes the preview ID. A change during or
after validation fails the transactional head check. A changed target or source
head returns `STALE_MERGE_PREVIEW` and publishes nothing.

Calls without preview or validation remain compatible. The core merge path still
captures and atomically rechecks both current heads, so direct publication is
race-safe. The complete preview-validation-publication sequence remains the
recommended agent workflow because it retains explicit evidence and rejects
semantically invalid combined programs before the target moves.

See [`merge-preview.md`](merge-preview.md) and
[`merge-validation.md`](merge-validation.md).

## 10. Versioned design context

Contracts and architecture documents are first-class immutable objects. They
may apply to a project, document, module, symbol, interface, test, or task.

An agent should receive the relevant context closure rather than the entire
repository:

```text
project invariants
+ module design
+ symbol contract
+ imported interfaces
+ directly relevant tests
```

Because context is pinned to revisions, review can reproduce the rules the agent
saw while it worked.

## 11. Determinism

The same validated program, language version, compiler identity, target, and
options must produce byte-identical canonical inputs and the same build key.

The same project, merge direction, common ancestor, and two branch heads must
produce the same merge preview ID and consequences. The same preview, merged
root, named target, ordered source hashes, and compiler binary must produce the
same merge validation ID.

Only final user-facing `weavec` is part of the public compiler contract. Bootstrap
stages must not leak into Jacquard's API.

## 12. Measured editing and review results

Real stdio MCP qualification has constructed, compiled, assembled, and executed:

- loop-carried arithmetic;
- multi-function call chains;
- heap-backed pointer and memory flows;
- a 354-node binary-search workload using 361 MCP calls and 356 revisions.

Those results established correctness but exposed round-trip and revision
amplification. The bounded transaction qualification therefore constructs a
balanced arithmetic program using:

- 246 structural operations;
- one batch write call;
- three reachable revisions instead of the 248-revision atomic equivalent;
- 418 total stored nodes including form-head atoms;
- authoritative native execution with exit status 80.

The transaction preserves full ordered audit evidence while reducing write calls
by more than 99% and revision count by more than 98% for that generated case.
Hardware-dependent elapsed time is recorded as evidence but is not a correctness
gate.

The real MCP review path additionally qualifies:

- compiler diagnostic to stable-node repair;
- historical node inspection after branch advancement;
- bounded forward and reverse revision diffs;
- clean merge preview and token-enforced publication;
- stale preview rejection after source-branch advancement;
- non-mutating conflict preview and conflict publication rejection.

## 13. Incremental compilation

Future module cache keys should include:

```text
module implementation hash
+ dependency interface hashes
+ compiler identity
+ target triple
+ optimization settings
```

Changing a private implementation changes its implementation hash but not
necessarily its public interface hash. Changing a public signature invalidates
dependent modules.

This should wait for real multi-module workloads and explicit interface objects.

## 14. Remaining boundaries

Current major omissions include:

- a formal machine-readable grammar and capability registry from `weavec`;
- merge-preview affected-test consequences;
- revisioned module-interface objects and dependency hashes;
- affected-test selection;
- sandboxed program execution tools;
- content-addressed node deduplication;
- distributed writers;
- ownership, borrow, and effect modeling beyond compiler support.

## 15. Next milestones

### M1 — measured agent ergonomics

- retain tool-order, failure, repair, validation, and review traces;
- compare single-edit and coherent-batch workflows on real agents;
- improve bounded inspection and grammar guidance from observed failures;
- add batch preview only if trace evidence shows it is needed.

### M2 — compiler capability contract

- consume a machine-readable capability and grammar registry from `weavec`;
- replace corpus inference without changing the MCP workflow;
- report compiler, language, target, manifest, and diagnostics compatibility.

### M3 — robust parallel development

- retain compiler-gated exact-candidate publication as the merge boundary;
- add explicit interface objects and versions;
- add edit scopes and affected-test selection;
- attach affected-test consequences to previews and validation evidence.

### M4 — execution and scale

- sandboxed `build_run` assertions;
- module-level incremental compilation;
- database integrity, backup, and artifact-retention operations;
- compact snapshots only when measurements justify them.
