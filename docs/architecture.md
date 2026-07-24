# Agent-native Weave frontend architecture

## 1. Thesis

A coding agent should not have to emit and maintain a complete source file.
Instead, it should operate on a typed program tree through a small set of tools:

```text
DISCOVER → INSPECT → MUTATE → VALIDATE → TEST → COMMIT → MERGE
```

The environment owns syntax, stable identities, scope, revision history, and
transactional safety. The model concentrates on local algorithmic decisions.

The authoritative representation is a versioned abstract syntax tree stored in
a database. Surface Weave, WIR, Rust, C, LLVM IR, and other forms are derived
artifacts.

## 2. Program structure

An S-expression is an ordered rooted n-ary tree. A first-child/next-sibling
encoding may implement it in memory, but that encoding is not the semantic
model. The database stores module snapshots and stable node IDs; future compact
snapshots may use a contiguous node array and string/type tables.

```text
workspace
└── project
    ├── program
    ├── module app
    │   ├── imports
    │   └── functions
    ├── module stdlib.arrays
    ├── contracts and documents
    ├── branches
    └── immutable revisions
```

## 3. Agent API

The intended MCP surface remains small:

### Discovery and inspection

- `find_symbols`
- `inspect_function`
- `inspect_node`
- `find_references`
- `get_context`
- `get_diagnostics`

### Mutation

- `create_module`
- `create_function`
- `insert_node`
- `replace_node`
- `delete_node`
- `add_import`

### Verification and history

- `validate`
- `compile`
- `run_tests`
- `create_branch`
- `commit`
- `merge`
- `checkout`
- `semantic_diff`

The prototype exposes these ideas as Python methods. An MCP adapter should be a
thin transport layer over the same service.

## 4. Immediate validation and syntax holes

Every inserted subtree must satisfy the grammar before it is persisted. A
malformed tool call returns a structured error and the branch head remains
unchanged.

Incomplete programs are represented with explicit holes:

```json
{"kind": "hole", "category": "statement", "expected_type": "i32"}
```

A hole is valid syntax but prevents finalization. This separates two questions:

1. Is the tree structurally well formed?
2. Is the program complete and semantically valid?

This allows an agent to build a function incrementally without ever storing a
broken parser state.

## 5. Modules, imports, and externs

`import stdlib.arrays` is a semantic dependency, not textual inclusion. It
resolves a module identity and a pinned interface version. Imports should
ultimately record:

- module identity;
- exact or compatible revision;
- public interface hash;
- alias and visibility;
- target/platform constraints.

An `extern` declares an ABI contract whose implementation is outside the Weave
program. A precompiled Weave module is different: it has a known interface,
optional AST/IR, and cached object artifact.

## 6. Persistence model

The prototype uses SQLite because it is embedded, transactional, portable, and
supports rich queries over symbols, revisions, and context.

Current core tables:

```text
projects
revisions
branches
module_snapshots
operations
documents
revision_documents
```

Each mutation creates a full immutable module snapshot. This is intentionally
simple. A production implementation can deduplicate immutable nodes or modules
by content hash.

### Fast compilation path

Compilation must not query one AST node at a time and must not regenerate text
only to lex and parse it again. The target path is:

```text
SQLite revision
→ load changed module snapshot in one operation
→ canonical semantic IR
→ backend
→ cached object
→ link
```

A future `ast_blob` can contain a compact node array, string table, type table,
and symbol table. The normalized/queryable representation serves agent edits;
the snapshot serves compilation.

## 7. History and backup

Revisions are immutable and form a DAG. A branch is only a named pointer to a
revision. Checkout moves a branch pointer; a user-facing revert should normally
create a new revision so the revert itself is reversible.

```text
R0 ── R1 ── R2
      ├── agent/foo: R3
      └── agent/bar: R4
```

The operation log explains how each revision was produced. Snapshot plus log
enables audit, semantic diff, undo of drafts, and reconstruction.

Internal history is not a physical backup. Production operation also requires
consistent database backups, integrity checks, and periodic canonical exports.

## 8. Parallel agents

Every agent receives:

- a base revision;
- a private branch;
- an edit scope;
- pinned interfaces;
- relevant contracts and design documents;
- tests and acceptance criteria.

Agents may read broadly but should write only inside the declared scope.
Interfaces can exist before implementations, allowing one agent to write
`foo()` against the declared `bar()` contract while another implements `bar()`.

The context used for a branch must be reproducible. Documents and interface
versions are therefore linked to revisions by hash or immutable identity.

## 9. Semantic three-way merge

Merge compares:

```text
base revision
our revision
their revision
```

The first prototype merges at module and function granularity:

- one branch changed and the other did not: take the change;
- both produced identical content: take either;
- both changed the same symbol differently: conflict;
- different symbols: merge automatically.

After structural merge, the complete program must pass:

1. grammar validation;
2. symbol resolution;
3. type checking;
4. contract/invariant checks;
5. compilation;
6. affected unit tests;
7. integration tests.

A text-level clean merge is insufficient.

## 10. Design context

Contracts and architecture documents are first-class immutable objects. They
may apply to a project, module, symbol, interface, test, or task.

An agent implementing `app.foo` receives only the relevant context closure:

```text
project invariants
+ app module design
+ app.foo contract
+ imported interfaces
+ directly relevant tests
```

This provides shared context without flooding a small model with the entire
repository.

## 11. Deterministic backends

The same validated AST, language version, backend version, target, and options
must produce byte-identical canonical output. Candidate backends include:

- surface Weave for human inspection and Git export;
- WIR for the current compiler pipeline;
- safe Rust for readable, memory-safe validation;
- C for portability and FFI;
- LLVM IR for production performance;
- WebAssembly for sandboxed execution.

Safe Weave should distinguish owned values, shared borrows, mutable borrows,
slices, arrays, and raw pointers. Only the explicitly unsafe subset should
require unsafe Rust or direct low-level code generation.

## 12. Incremental compilation

Cache keys should include:

```text
module implementation hash
+ dependency interface hashes
+ compiler version
+ target triple
+ optimization settings
```

Changing a private function changes the implementation hash but not necessarily
the interface hash. Dependents then reuse their object artifacts. Changing a
public signature invalidates dependent modules.

## 13. Prototype boundaries

The current implementation deliberately omits:

- a networked MCP server;
- parsing existing `.weave` files into the database;
- WIR/LLVM compilation;
- content-addressed node deduplication;
- ownership and borrow checking;
- fine-grained expression-level merge;
- executable contract checking;
- distributed writers.

These should be added only after the core editing and merge experiments show
clear value with real agents.

## 14. Next milestones

### M1 — prove editing ergonomics

- MCP adapter over `Workspace`;
- import/export for the current surface grammar;
- Fibonacci, GCD, Collatz, factorial, power, Ackermann, and sorting tasks;
- record tool calls, validation failures, repairs, tokens, and correctness.

### M2 — real compiler bridge

- emit current WIR deterministically;
- invoke `weavec2` for compile and run;
- cache artifacts by revision and target;
- compare direct text generation against AST tools.

### M3 — robust parallel development

- explicit interface objects and versions;
- edit scopes;
- semantic diffs;
- merge previews and conflict diagnostics;
- affected-test selection.

### M4 — safe systems model

- arrays, slices, structs, ownership, borrows, and effects;
- safe Rust backend;
- extern and precompiled module support;
- compact binary AST snapshots.
