# Agent-native Weave frontend architecture

## 1. Thesis

A coding agent should not have to emit and maintain a complete source file.
Instead, it should operate on a versioned program tree through a compact tool
surface:

```text
DISCOVER → INSPECT → MUTATE → VALIDATE → TEST → COMMIT → MERGE
```

The environment owns syntax, stable identities, scope, revision history, and
transactional safety. The model concentrates on local algorithmic decisions.

The authoritative editing representation is a versioned abstract syntax tree in
a database. Surface Weave, WIR, LLVM IR, and native objects are deterministic
derivatives. The canonical language implementation and completed-program
validator is [`weavec`](https://github.com/ahojukka5/weavec).

## 2. Program structure

An S-expression is an ordered rooted n-ary tree. A first-child/next-sibling
encoding may implement it in memory, but that encoding is not the semantic
model. The database stores immutable snapshots and stable node IDs.

```text
workspace
└── project
    ├── program documents
    ├── modules and functions
    ├── contracts and design context
    ├── branches
    └── immutable revisions
```

## 3. Agent API

The intended MCP surface is deliberately small.

### Discovery and inspection

- `grammar_help`
- `program_list`
- `program_render`
- `node_find`
- `node_inspect`
- `context_get`

### Mutation

- `program_create`
- `program_import`
- `node_create_form`
- `node_add_atom`
- `node_set_atom`
- `node_move`
- `node_wrap`
- `node_delete`
- `context_add`

### Verification and history

- `program_validate`
- `branch_create`
- `branch_list`
- `branch_history`
- `branch_merge`

The MCP server is a transport layer over the same workspace services used by the
Python API.

## 4. Validation and incomplete programs

Every persisted mutation must preserve structural validity. A failed operation
returns a structured error and does not advance the branch head.

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

The MCP environment must not maintain a second handwritten copy of the complete
surface grammar. Until `weavec` exposes a machine-readable registry, grammar
help is inferred from its `test/correctness/surface` corpus.

## 5. Modules, imports, and externs

An import is a semantic dependency, not textual inclusion. A production module
reference should record:

- module identity;
- exact or compatible revision;
- public interface hash;
- alias and visibility;
- target and platform constraints.

An `extern` declares an ABI contract whose implementation is outside the Weave
program. A precompiled Weave module is different: it has a known interface,
optional semantic representation, and cached compiled artifacts.

## 6. Persistence model

The prototype uses SQLite because it is embedded, transactional, portable, and
supports rich queries over revisions and context.

Core concepts include:

```text
projects
revisions
branches
module snapshots
operations
documents
revision documents
```

Each mutation currently creates a complete immutable snapshot. This is simple
and auditable. A production implementation can deduplicate immutable nodes or
modules by content hash.

### Compilation boundary

Compilation must not query one AST node at a time or regenerate source only to
parse it again. The target path is:

```text
SQLite revision
→ load changed module snapshot
→ canonical semantic representation
→ weavec compiler boundary
→ cached object
→ link
```

A future compact snapshot can contain a node array, string table, type table,
and symbol table. The normalized representation serves agent edits; the compact
snapshot serves compilation.

## 7. History and backup

Revisions are immutable and form a DAG. A branch is a named pointer to a
revision. User-facing revert normally creates a new revision so the revert is
itself reversible.

```text
R0 ── R1 ── R2
      ├── agent/foo: R3
      └── agent/bar: R4
```

The operation log explains how each revision was produced. Snapshot plus log
enables semantic diff, audit, merge, and reconstruction. Internal history is not
a physical backup; production operation also requires consistent database
backups and integrity checks.

## 8. Parallel agents

Every agent receives:

- a base revision;
- a private branch;
- an edit scope;
- pinned interfaces;
- relevant contracts and design context;
- tests and acceptance criteria.

Agents may read broadly but should write only inside their declared scope.
Interfaces can exist before implementations, allowing parallel work against
pinned contracts.

## 9. Semantic three-way merge

Merge compares a base revision with both branch heads.

- one branch changed a node and the other did not: take the change;
- both produced identical content: take either;
- both changed the same identity differently: conflict;
- independent node changes: merge automatically.

A text-level clean merge is insufficient. The merged program must pass
structural validation and, when coherent, compiler validation through `weavec`.
Later stages should also perform symbol resolution, type checking, contract
checks, compilation, and affected tests.

## 10. Versioned design context

Contracts and architecture documents are first-class immutable objects. They
may apply to a project, document, module, symbol, interface, test, or task.

An agent receives the relevant context closure rather than the entire repository:

```text
project invariants
+ module design
+ symbol contract
+ imported interfaces
+ directly relevant tests
```

Because context is pinned to revisions, later review can reproduce the rules an
agent saw while it worked.

## 11. Deterministic compiler boundary

The same validated program, language version, compiler version, target, and
options must produce byte-identical canonical output. The active compiler chain
is external to this repository:

```text
weavec0 → weavec1 → weavec-bootstrap → weavec
```

Only the final user-facing `weavec` command is part of the MCP validation
contract. Bootstrap stages must not leak into this repository's public API.

## 12. Incremental compilation

Artifact cache keys should include:

```text
module implementation hash
+ dependency interface hashes
+ compiler version
+ target triple
+ optimization settings
```

Changing a private implementation changes its implementation hash but not
necessarily its public interface hash. Changing a public signature invalidates
dependent modules.

## 13. Prototype boundaries

The current implementation deliberately omits:

- direct AST-to-compiler integration;
- a formal machine-readable grammar registry;
- content-addressed node deduplication;
- ownership and borrow checking;
- fine-grained expression-level merge;
- executable contract checking;
- distributed writers;
- build, run, package, and artifact management.

These should be added only after the editing and merge experiments demonstrate
clear value with real coding agents.

## 14. Next milestones

### M1 — editing ergonomics

- evaluate atomic tools on representative Weave programs;
- record tool calls, validation failures, repairs, and correctness;
- improve bounded inspection and grammar guidance.

### M2 — canonical compiler bridge

- consume a machine-readable grammar registry from `weavec` when available;
- invoke `weavec --frontend` through the stable adapter;
- add compile, run, and test tools around released compiler binaries;
- cache artifacts by revision and target.

### M3 — robust parallel development

- explicit interface objects and versions;
- edit scopes;
- semantic diffs and merge previews;
- conflict diagnostics;
- affected-test selection.

### M4 — safe systems model

- arrays, slices, structs, ownership, borrows, and effects;
- extern and precompiled module support;
- compact binary snapshots;
- auditable sandboxed execution.
