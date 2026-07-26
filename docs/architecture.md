# Jacquard architecture

## 1. Thesis

A coding agent should not have to emit and maintain a complete source file.
Instead, it operates on a versioned program tree through a compact tool surface:

```text
DISCOVER → INSPECT → MUTATE → PREFLIGHT → MERGE → BUILD → TEST
```

Jacquard owns syntax-tree identity, immutable revisions, transactional safety,
canonical source materialization, target-authoritative merge admission, build
provenance, and reviewed branch publication. The authoritative language
implementation and native compiler remains
[`weavec`](https://github.com/ahojukka5/weavec).

## 2. Program and project structure

An S-expression is an ordered rooted n-ary tree. The database stores immutable
snapshots and stable node IDs.

```text
workspace
└── project
    ├── program documents
    ├── revisioned named build targets
    ├── revisioned merge policy and design context
    ├── branches
    ├── immutable revisions and operations
    └── verified build artifacts
```

Surface Weave, WIR, LLVM IR, bitcode, objects, and native executables are
derivatives of pinned program revisions. A prospective merge candidate is an
in-memory validated state, not a temporary revision or persisted artifact.

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
- `merge_policy_get`
- `branch_merge_preflight`
- `branch_merge_preview`
- `branch_merge_impact`
- `branch_merge_validate`
- `branch_merge_validate_affected`
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
- `merge_policy_set`

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

The MCP server is a transport over the same workspace, policy, preview, impact,
validation, and compiler-bridge services used internally.

## 4. Structural write modes

### Single-node edits

Use one-node tools while exploring or repairing. Each successful call publishes
one immutable revision.

### Bounded edit transactions

Use `node_apply_batch` after one coherent local structure is known. A batch is a
flat ordered list of 1–256 ordinary structural operations and may use temporary
aliases for nodes created earlier in the request.

A batch:

- pins one document at one branch head;
- optionally checks an expected revision;
- applies operations in memory;
- validates the complete tree once;
- writes one immutable snapshot and ordered operation rows;
- compare-and-set advances the branch;
- rolls back completely on failure.

The batch API must never become unbounded nested AST replacement. See
[`edit-transactions.md`](edit-transactions.md).

## 5. Validation and incomplete programs

Every persisted structural write preserves tree validity:

- legal node shapes and atom values;
- stable unique node IDs;
- ordered children;
- no move cycles;
- deterministic rendering.

Semantic completeness remains compiler authority:

```text
weavec --frontend output.wir input0.weave input1.weave ...
```

`program_validate` checks one document. `build_target_validate` checks one
revisioned ordered source set. Merge validation checks named targets from the
exact clean in-memory candidate.

Jacquard does not maintain a handwritten copy of the complete surface grammar.
Until `weavec` exposes a machine-readable registry, grammar guidance is inferred
from its correctness corpus.

## 6. Persistence and publication

The prototype uses SQLite because it is embedded, transactional, portable, and
supports revision, context, and audit queries.

Core concepts:

```text
projects
revisions
branches
module snapshots
operations
context documents
revision documents
```

Snapshots and revisions are immutable. A branch is a named pointer to one
revision. The operation log explains how each revision was produced.

Publication modes:

- one-node edits use one transaction each;
- edit batches use one transaction for all operations and one compare-and-set;
- policy changes publish one unchanged structural snapshot plus an immutable
  policy context document reference and `set_merge_policy` audit operation;
- merge publication rechecks both captured heads, writes the validated merged
  state, records both parents, and advances only the target.

Preview, impact, preflight, and candidate compiler validation are outside
persistence. They use in-memory state and private temporary compiler files and
retain only bounded response evidence. No preview or validation attempt creates
a schema row.

Revisioned merge policy reuses existing context-document and operation tables.
No schema migration is required.

## 7. Compiler and artifact boundary

Pinned-revision compilation:

```text
SQLite revision
→ canonical .weave sources and node maps
→ final weavec
→ validated manifest and diagnostics
→ verified content-derived artifact store
```

Prospective merge validation:

```text
exact in-memory candidate
→ candidate named targets + ordered sources
→ weavec --frontend
→ bounded source/compiler/WIR hash evidence
```

The candidate path creates no revision, executable, build manifest, retained
diagnostics artifact, or retained WIR.

`weavec` owns language lowering, WIR, LLVM generation, runtime selection, object
generation, linking, and native output. Jacquard owns revision pinning, source
order, canonical materialization, node maps, protocol validation, artifact
hashing, cache identity, merge policy, and atomic publication.

Build artifacts are admitted only when paths, hashes, compiler manifest,
diagnostics protocol, source order, target, output, and requested build identity
all agree. Concurrent candidates are serialized per build ID; an existing
verified success wins.

## 8. Revisioned target-authoritative merge policy

A merge policy is an immutable project-scoped context document referenced by a
`set_merge_policy` operation. It controls:

- whether exact preflight replay is required;
- whether every affected surviving target must validate;
- whether uncovered-document overrides are allowed;
- the maximum affected-target compiler fanout.

Policy lookup walks first-parent history. This aligns admission authority with
merge topology:

```text
merge revision
├── parent1: current target head  ← authoritative policy history
└── parent2: incoming source head ← visible, non-authoritative policy history
```

A source branch may publish a permissive policy, but it cannot weaken the target.
Preflight and merge results expose both policies and set
`source_policy_ignored=true` when hashes differ.

To loosen a protected target, publish `merge_policy_set` directly on that target.
The policy revision advances the target head and invalidates old preview and
preflight identities.

When no policy is configured, legacy direct, one-target, and all-target merge
modes remain available. See [`merge-policy.md`](merge-policy.md).

## 9. Parallel agents and merge admission

Every agent receives:

- a base revision;
- a private branch;
- an edit scope;
- pinned interfaces and context;
- tests and acceptance criteria.

Three-way stable-ID merge rules:

- one branch changed an identity and the other did not: take the change;
- both produced identical content: take either;
- both changed the same identity differently: conflict;
- independent changes: merge automatically.

### Structural preview

`branch_merge_preview` computes the stable-ID merge without publication.
`weave-merge-preview-v1` binds project, merge direction, common ancestor, target
head, and source head. Clean previews return compact consequences; conflicts
return exact paths.

### Directional impact

`branch_merge_impact` compares the current target with the prospective merged
state. It reports only changes introduced by the source, maps those changes to
revisioned named targets, and exposes changed documents with no surviving target
coverage.

### One-target and all-target validation

`branch_merge_validate` validates one candidate target.

`branch_merge_validate_affected` validates every affected target surviving in the
candidate, in deterministic name order. It skips removed targets, aggregates all
failures, and performs zero compiler work when uncovered documents block the
candidate. Its validation-set identity binds the effective fanout ceiling.

### One-call preflight

`branch_merge_preflight` composes:

```text
target policy + source policy visibility
+ preview
+ directional impact
+ coverage
+ complete affected-target validation
```

`weave-merge-preflight-v1` binds both policy hashes, source-policy disposition,
preview and merged root, impact summary, validation-set identity, and uncovered
policy. It returns exact `branch_merge` publication arguments including
`preflight_id`.

Preflight is evidence, not authorization. Policy-aware publication recomputes
preflight against current policy and heads, compares exact identity, enforces
readiness, and then publishes using its validated preview. The recomputed
validation set is reused; Jacquard does not perform a redundant second compiler
fanout for the identical candidate.

Both heads are finally checked in the same `BEGIN IMMEDIATE` transaction that
writes the two-parent merge revision. A change before replay changes preflight
identity; a change during or after validation fails the transactional head check.

See [`merge-preflight.md`](merge-preflight.md),
[`merge-validation-set.md`](merge-validation-set.md), and
[`merge-preview.md`](merge-preview.md).

## 10. Versioned design context

Contracts, architecture notes, and policies are immutable context objects. They
may apply to project, document, module, symbol, interface, test, or task.

An agent should receive the relevant context closure:

```text
project invariants and target policy
+ module design
+ symbol contract
+ imported interfaces
+ directly relevant tests
```

Because context is pinned to revisions, review can reproduce the rules and policy
seen by the agent.

## 11. Determinism

The same validated program, language version, compiler identity, target, and
options produce byte-identical canonical inputs and the same build key.

Merge identities are layered:

- same branch direction and heads → same preview ID;
- same preview and target graph → same impact;
- same target/source/compiler hashes → same validation IDs;
- same effective fanout and complete target set → same validation-set ID;
- same policies, candidate, impact, validation set, and uncovered policy → same
  preflight ID.

Only final user-facing `weavec` is part of the public compiler contract. Bootstrap
stages must not leak into Jacquard's API.

## 12. Measured editing and review results

Real stdio MCP qualification has constructed, compiled, and executed:

- loop-carried arithmetic;
- multi-function call chains;
- heap-backed pointer and memory flows;
- a 354-node binary-search workload;
- a 418-node batch workload with exit status 80;
- exact candidate merge validation and native execution;
- all-affected-target pass/fail and coverage aggregation;
- one-call merge preflight with ready, invalid, uncovered, and override outcomes;
- target-authoritative revisioned merge policy.

The bounded batch reduced write calls by more than 99% and reachable revision
count by more than 98% for its generated case while preserving ordered audit
rows.

Policy qualification proved:

- strict target policy required exact preflight replay;
- a permissive incoming policy was visible but ignored;
- protected merges built and executed with exit statuses 30 and 31;
- a target fanout ceiling of one rejected two affected targets before compilation;
- only a direct target policy revision could relax the ceiling;
- the relaxed protected merge built and executed with exit status 32;
- historical policy lookup reproduced the earlier ceiling.

The review path also qualifies compiler-guided stable-node repair, historical
inspection, forward/reverse revision diffs, stale preview rejection, and
non-mutating conflict handling.

## 13. Incremental compilation

Future module cache keys should include:

```text
module implementation hash
+ dependency interface hashes
+ compiler identity
+ target triple
+ optimization settings
```

Changing private implementation may preserve an interface hash; changing public
signature invalidates dependents. This should wait for real multi-module
workloads and explicit interface objects.

## 14. Remaining boundaries

Major omissions include:

- a formal machine-readable grammar and capability registry from `weavec`;
- revisioned module-interface objects and dependency hashes;
- affected-test selection and preview consequences;
- sandboxed program execution tools;
- content-addressed node deduplication;
- distributed writers;
- ownership, borrow, and effect modeling beyond compiler support.

## 15. Next milestones

### M1 — measured agent ergonomics

- retain tool-order, failure, repair, policy, validation, and review traces;
- compare single-edit and coherent-batch workflows on real agents;
- improve bounded inspection and grammar guidance from observed failures.

### M2 — compiler capability contract

- consume a machine-readable capability and grammar registry from `weavec`;
- replace corpus inference without changing MCP workflow;
- report compiler, language, target, manifest, and diagnostics compatibility.

### M3 — robust parallel development

- retain target-authoritative revisioned policy and exact preflight replay;
- add explicit interface objects and versions;
- add edit scopes and affected-test selection;
- attach affected-test consequences to preflight evidence;
- retain merge admission hashes in immutable audit evidence.

### M4 — execution and scale

- sandboxed `build_run` assertions;
- module-level incremental compilation;
- database integrity, backup, and artifact-retention operations;
- compact snapshots only when measurements justify them.
