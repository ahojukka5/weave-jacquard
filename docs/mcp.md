# weave-mcp

## Goal

`weave-mcp` lets an agent construct, validate, merge, and build Weave programs
without emitting a large nested JSON tree or balancing S-expression parentheses.
The write API is atomic: one form, atom, move, wrap, or deletion per call.

The database owns node identity and revision history. Canonical `.weave` source
is generated deterministically when validation or compilation requires it.

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
  → canonical source + weave-node-map-v1
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
omits annotations. `program_build` generates the canonical source and a sidecar
map containing UTF-8 byte and line/column spans for every node.

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
- `program_build` builds a pinned revision into a native executable.

`program_import` is not the preferred agent write path.

### Builds

#### `program_build`

Inputs:

```text
project
document
branch = "main"
revision_id = optional exact revision
target = optional target triple
```

When `revision_id` is omitted, the branch head is resolved once before rendering.
The operation returns a build manifest containing the build ID, pinned revision,
status, hashes, and artifact paths. It does not execute the output program.

#### `build_get`

Returns a stored build manifest and artifact paths by hexadecimal build ID.
Inspecting an existing build does not require the compiler binary.

A successful build contains canonical source, node map, compiler manifest,
diagnostics, frontend manifest, and executable. A failed build contains the
diagnostic artifacts but no executable.

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
→ program_create
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
- The final executable exists only on success.
- Build diagnostics preserve compiler stdout, stderr, timeout state, and return
  code.
- Machine-readable compiler spans will later be mapped to node IDs through the
  source map.
- Program execution remains a separate future sandboxed operation.

## Current boundary

Atomic mutations guarantee a structurally sound tree: unique IDs, valid node
shapes, ordered children, and no move cycles. A partially constructed Weave form
may still be incomplete. Use `grammar_help` while building,
`program_validate` when a coherent unit is ready, and `program_build` only for a
revision intended to become a native artifact.
