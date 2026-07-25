# weave-mcp

## Goal

`weave-mcp` lets an agent construct, validate, merge, and build Weave programs
without emitting a large nested JSON tree or balancing S-expression parentheses.
The write API is atomic: one form, atom, move, wrap, or deletion per call.

The database owns node identity and revision history. Canonical `.weave` sources
are generated deterministically when validation or compilation requires them.

## Grammar and compiler authority

The MCP server deliberately does not duplicate the full Weave grammar or native
toolchain.

`grammar_help` scans the configured `weavec` checkout under
`test/correctness/surface` and indexes forms actually used there. This index is
construction guidance. The authoritative language check is:

```text
program_validate
  → canonical source
  → weavec --frontend
```

The authoritative native build is:

```text
program_build
  → pin immutable revision
  → ordered canonical sources + one weave-node-map-v1 per source
  → weavec build
  → executable and manifests
```

`weave_frontend` never invokes LLVM tools or selects a runtime archive. The
compiler package owns those details.

Set `WEAVEC_SOURCE_ROOT` to enable corpus-backed grammar help. Set `WEAVEC_BIN`
when the compiler is not available as `weavec` on `PATH`. `WEAVE_BUILD_ROOT`
selects the artifact store.

## Stable IDs and compiler source

Every list and atom receives a stable ID such as `n_3a12cce48fe14f99`.

- editing an atom preserves its ID;
- moving a node preserves its ID;
- new nodes receive new IDs;
- branches retain IDs inherited from their base revision;
- merge uses IDs rather than line numbers.

`program_render(annotated=true)` and `node_inspect` expose IDs. Canonical source
omits annotations. `program_build` generates a separate canonical source and
sidecar map for every selected database document. Each map contains UTF-8 byte
and line/column spans for every node in that document.

## Tools

### Help and grammar

- `weave_help(topic)` explains workflows, IDs, writes, reads, and validation.
- `grammar_help(form, query, parent_form)` searches the `weavec` surface corpus.

Recommended calls include:

```text
grammar_help(form="fn")
grammar_help(form="while")
grammar_help(parent_form="program")
grammar_help(query="ptr")
```

### Projects and branches

- `project_initialize`
- `branch_create`
- `branch_list`
- `branch_history`
- `branch_merge`

Each mutation creates an immutable revision. Branch merge is a three-way merge
of stable node identities. Independent insertions into the same list are kept;
incompatible edits to the same atom or subtree produce a conflict.

### Program documents

- `program_create` creates the program, name, and version forms.
- `program_list` lists documents and root IDs.
- `program_render` returns canonical or annotated Weave.
- `program_validate` runs structural checks and the configured compiler frontend.
- `program_import` imports complete source for migration and fixtures.
- `program_build` builds an ordered document set from a pinned revision.

`program_import` is not the preferred agent write path.

### Builds

#### `program_build`

Inputs:

```text
project
document                         primary source
additional_documents = optional ordered list
branch = "main"
revision_id = optional exact revision
target = optional target triple
```

Example:

```text
program_build(
  project="demo",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"],
  branch="main"
)
```

The primary document is always first. Additional documents are passed to
`weavec build` in exactly the supplied order. The server does not sort them and
does not silently include every document in the project. Duplicates are rejected.
Every selected document must exist in the same pinned revision.

When `revision_id` is omitted, the branch head is resolved once before rendering.
The operation returns `weave-frontend-build-manifest-v2`, containing the build
ID, pinned revision, ordered document records, status, hashes, and artifact
paths. It does not execute the output program.

The corresponding CLI form is:

```text
weave-build --db weave.db build demo main.weave \
  --source library.weave \
  --source platform.weave
```

Each repeated `--source` preserves order.

#### `build_get`

Returns a stored build manifest and artifact paths by hexadecimal build ID.
Inspecting an existing build does not require the compiler binary.

A successful build contains:

- all canonical sources under `sources/`;
- all node maps under `source-maps/`;
- compiler manifest;
- raw compiler diagnostics;
- node-mapped bridge diagnostics;
- frontend build manifest;
- executable.

A failed build contains diagnostic artifacts but no executable. For compatibility,
`artifacts.source` and `artifacts.node_map` still identify the primary document;
`artifacts.sources` and `artifacts.node_maps` contain the complete ordered set.

### Atomic node writes

- `node_create_form(parent_id, head, position)`
- `node_add_atom(parent_id, kind, value, position)`
- `node_set_atom(node_id, value)`
- `node_move(node_id, new_parent_id, position)`
- `node_wrap(node_id, head)`
- `node_delete(node_id)`

Atom kinds are `symbol`, `string`, `integer`, `float`, and `boolean`. Positions
are zero-based and default to append.

### Inspection

- `node_inspect(node_id, depth)` returns a local annotated subtree.
- `node_find(head, kind, value)` locates exact node IDs.

Reading may return a larger local subtree. Writing remains atomic.

### Shared context

- `context_add` stores project-, document-, or symbol-scoped design material.
- `context_get` retrieves context pinned to the current branch revision.

This lets parallel agents share interface contracts and design decisions without
relying on an unversioned prompt.

## Recommended complete workflow

```text
project_initialize
→ program_create / program_import
→ grammar_help
→ atomic node edits
→ node_inspect
→ program_validate
→ branch_merge
→ program_build
→ build_get
```

## Failure semantics

- Validation or build failure does not mutate the program revision.
- `program_build` never advances a branch.
- Missing or duplicate selected documents fail before compilation.
- The final executable exists only on compiler and protocol success.
- Build diagnostics preserve compiler stdout, stderr, timeout state, and return
  code.
- Every canonical compiler span is matched against the node map for the exact
  source document named by the compiler.
- A secondary-document diagnostic receives that document's `document` and
  `node_id`, not the primary document's mapping.
- Spanless, ambiguous, and non-canonical locations remain unmapped.
- Program execution remains a separate future sandboxed operation.

## Current boundary

Atomic mutations guarantee a structurally sound tree: unique IDs, valid node
shapes, ordered children, and no move cycles. A partially constructed Weave form
may still be incomplete. Use `grammar_help` while building,
`program_validate` when a coherent unit is ready, and `program_build` only for a
revision intended to become a native artifact.
