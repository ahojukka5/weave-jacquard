# weave-mcp

## Goal

`weave-mcp` lets an agent construct and edit Weave programs without emitting a
large nested JSON tree or balancing S-expression parentheses. The write API is
atomic: one form, atom, move, wrap, or deletion per call.

The database owns node identity and revision history. Canonical `.weave` source
is generated deterministically when needed.

## Grammar authority

The MCP server deliberately does not duplicate the full Weave grammar.

`grammar_help` scans the configured `weavec2` checkout under
`test/correctness/surface` and indexes the forms actually used there. For each
form it reports:

- observed argument counts;
- observed parent forms;
- compact examples;
- the source files containing those examples.

This index is guidance for incremental construction. The authoritative check is
`program_validate`, which renders canonical source and runs:

```text
weavec2 --frontend output.wir input.weave
```

Set `WEAVEC2_SOURCE_ROOT` and `WEAVEC2_BIN` to enable both parts.

## Stable IDs

Every list and atom receives a stable ID such as `n_3a12cce48fe14f99`.

- editing an atom preserves its ID;
- moving a node preserves its ID;
- new nodes receive new IDs;
- branches retain IDs inherited from their base revision;
- merge uses IDs rather than line numbers.

`program_render(annotated=true)` and `node_inspect` expose IDs. Canonical source
omits the annotations.

## Tools

### Help and grammar

- `weave_help(topic)` explains workflows, IDs, writes, reads, and validation.
- `grammar_help(form, query, parent_form)` searches the weavec2 surface corpus.

Recommended calls include:

```text
grammar_help(form="fn")
grammar_help(form="while")
grammar_help(parent_form="program")
grammar_help(query="ptr")
```

### Project and branches

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
- `program_validate` runs structural checks and the configured weavec2 frontend.
- `program_import` imports complete source for migration and fixtures.

`program_import` is not the preferred agent write path.

### Atomic node writes

- `node_create_form(parent_id, head, position)`
- `node_add_atom(parent_id, kind, value, position)`
- `node_set_atom(node_id, value)`
- `node_move(node_id, new_parent_id, position)`
- `node_wrap(node_id, head)`
- `node_delete(node_id)`

Atom kinds are `symbol`, `string`, `integer`, `float`, and `boolean`.
Positions are zero-based and default to append.

### Inspection

- `node_inspect(node_id, depth)` returns a local annotated subtree.
- `node_find(head, kind, value)` locates exact node IDs.

Reading may return a larger local subtree. Writing remains atomic.

### Shared context

- `context_add` stores project-, document-, or symbol-scoped design material.
- `context_get` retrieves context pinned to the current branch revision.

This lets parallel agents share interface contracts and design decisions without
relying on an unversioned prompt.

## Example construction

To create `(return (const_i32 42))` inside a known `do` block:

```text
node_create_form(parent_id=do_id, head="return")
→ return_id

node_create_form(parent_id=return_id, head="const_i32")
→ constant_id

node_add_atom(parent_id=constant_id, kind="integer", value=42)
```

No call contains a nested subtree. Each step returns a new revision, node IDs,
and a local grammar hint.

## Current boundary

Atomic mutations guarantee a structurally sound tree: unique IDs, valid node
shapes, ordered children, and no move cycles. A partially constructed Weave form
may still be incomplete. Use `grammar_help` while building and
`program_validate` when a coherent unit is ready.

A later weavec2 change may expose a machine-readable grammar registry. The MCP
help provider can consume that registry without changing its public tool API.
