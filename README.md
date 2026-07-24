# weave_frontend

`weave_frontend` is an experimental **agent-native programming environment**
for Weave. A coding agent edits a versioned S-expression tree through small MCP
tool calls instead of generating and maintaining an entire source file.

The main executable is **`weave-mcp`**. It provides an atomic write API, stable
node IDs, immutable revision history, parallel branches, grammar discovery, and
validation through the existing `weavec2` frontend.

> The model decides what program to build. The environment owns syntax-tree
> structure, identities, history, and transactional safety.

## Why

Small language models can often understand an algorithm while still failing to
reliably emit deeply nested S-expressions. A missing parenthesis, stale source
location, or oversized JSON subtree can ruin an otherwise correct solution.

`weave-mcp` moves that mechanical work out of the model:

- one tool call creates one form, atom, move, wrap, or deletion;
- every list and atom receives a stable `n_*` ID;
- failed operations do not advance the branch head;
- larger local subtrees may be inspected without being rewritten;
- revisions and design context are stored in SQLite;
- multiple agents can work on independent branches;
- completed programs are checked by `weavec2 --frontend`;
- canonical Weave source remains a deterministic export format.

## Status

This repository is a runnable prototype. It currently contains:

1. **`weave-mcp`** — the primary grammar-neutral MCP server for atomic
   S-expression construction.
2. **Typed AST prototype** — the earlier, smaller frontend used to prove
   immutable revisions, validation, context, and semantic merge.

The MCP server is not yet a replacement for `weavec2`. It uses `weavec2` as the
authoritative completed-program validator.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Build `weavec2` separately and point the MCP server to its source checkout and
binary:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVEC2_SOURCE_ROOT="../weavec2"
export WEAVEC2_BIN="../weavec2/build/weavec2"
```

Run the server over MCP stdio:

```bash
weave-mcp
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `WEAVE_DB_PATH` | SQLite program database | `weave.db` |
| `WEAVEC2_SOURCE_ROOT` | `weavec2` checkout used by grammar help | unset |
| `WEAVEC2_BIN` | built `weavec2` executable used for validation | unset |

Tree editing works without `weavec2`, but grammar examples and authoritative
program validation require the corresponding configuration.

## MCP client configuration

A typical stdio client configuration looks like this:

```json
{
  "mcpServers": {
    "weave": {
      "command": "/path/to/venv/bin/weave-mcp",
      "env": {
        "WEAVE_DB_PATH": "/path/to/project/weave.db",
        "WEAVEC2_SOURCE_ROOT": "/path/to/weavec2",
        "WEAVEC2_BIN": "/path/to/weavec2/build/weavec2"
      }
    }
  }
}
```

The exact outer configuration format depends on the MCP client. The command and
environment variables are the important parts.

## Recommended agent workflow

```text
weave_help
→ project_initialize
→ program_create
→ grammar_help
→ node_create_form / node_add_atom
→ node_inspect
→ program_validate
→ branch_merge
```

The agent should call `grammar_help` before using an unfamiliar Weave form and
should prefer atomic writes over `program_import`.

## Atomic construction example

The following sequence builds a minimal program equivalent to:

```lisp
(program
  (name "answer")
  (version "0.1")
  (entry main)
  (fn main
    (params)
    (returns i32)
    (do
      (return (const_i32 42)))))
```

First create the project and the initial program document:

```text
project_initialize(project="demo")
program_create(
  project="demo",
  branch="main",
  document="main",
  program_name="answer"
)
```

`program_create` returns the root program node ID. Use that ID as
`program_id` below.

```text
node_create_form(
  project="demo",
  branch="main",
  document="main",
  parent_id=program_id,
  head="entry"
)
```

The call returns `entry_id`. Add its symbol atom:

```text
node_add_atom(
  project="demo",
  branch="main",
  document="main",
  parent_id=entry_id,
  kind="symbol",
  value="main"
)
```

Create the function and its name:

```text
node_create_form(parent_id=program_id, head="fn", ...)
→ fn_id

node_add_atom(parent_id=fn_id, kind="symbol", value="main", ...)
```

Create the empty parameter form, return type, and body:

```text
node_create_form(parent_id=fn_id, head="params", ...)

node_create_form(parent_id=fn_id, head="returns", ...)
→ returns_id
node_add_atom(parent_id=returns_id, kind="symbol", value="i32", ...)

node_create_form(parent_id=fn_id, head="do", ...)
→ do_id
```

Create the return expression one form at a time:

```text
node_create_form(parent_id=do_id, head="return", ...)
→ return_id

node_create_form(parent_id=return_id, head="const_i32", ...)
→ const_id

node_add_atom(parent_id=const_id, kind="integer", value=42, ...)
```

Inspect the local result and validate the complete program:

```text
node_inspect(
  project="demo",
  branch="main",
  document="main",
  node_id=fn_id,
  depth=6
)

program_validate(
  project="demo",
  branch="main",
  document="main"
)
```

Every mutation creates a new immutable revision and returns stable node IDs for
subsequent calls.

## Help and grammar discovery

### `weave_help`

Use `weave_help` to discover the recommended workflow and tool categories:

```text
weave_help(topic="workflow")
weave_help(topic="write")
weave_help(topic="read")
weave_help(topic="ids")
weave_help(topic="validation")
```

### `grammar_help`

`grammar_help` searches the configured
`weavec2/test/correctness/surface` corpus instead of maintaining another
handwritten copy of the language grammar.

```text
grammar_help(form="fn")
grammar_help(form="while")
grammar_help(parent_form="program")
grammar_help(query="ptr")
grammar_help(query="contract")
```

It reports observed shapes, parent forms, arities, examples, and source fixture
paths. This is guidance for construction. The final normative check is always:

```text
program_validate → weavec2 --frontend
```

## Stable node IDs

Every list and atom has an internal stable ID such as `n_...`.

ID rules:

- creating a node assigns a new ID;
- editing an atom preserves its ID;
- moving a node preserves its ID;
- wrapping creates a new wrapper ID and preserves the wrapped node ID;
- deleting removes the node and its subtree;
- branches preserve IDs inherited from their base revision;
- merge compares nodes by stable identity, not by source line.

Canonical rendering omits IDs. Agent rendering can expose them:

```lisp
(@n_a1b2
  (program
    (@n_c3d4 (name "answer"))
    (@n_e5f6 (version "0.1"))))
```

Use:

```text
program_render(annotated=true)
```

Set `annotate_atoms=true` when atom-level IDs are also needed.

## Reading and editing existing programs

Use semantic node operations instead of line-oriented editing:

```text
program_list
node_find
node_inspect
node_set_atom
node_move
node_wrap
node_delete
program_render
```

`node_inspect` intentionally returns a bounded local subtree. The agent may read
more context by increasing `depth`, but ordinary writes remain atomic.

`program_import` parses existing source into the database and assigns IDs. It is
intended for migration, fixtures, and experiments—not as the default agent write
path.

## Parallel agents and merge

Each agent should work on its own database branch:

```text
branch_create(project="demo", branch="agent/foo")
branch_create(project="demo", branch="agent/bar")
```

Agents inherit the same program IDs and versioned design context from their
common base. They can then make independent atomic changes.

Merge with:

```text
branch_merge(
  project="demo",
  target_branch="main",
  source_branch="agent/foo"
)
```

The merge is a three-way tree merge using stable node identities. Conflicting
changes are rejected instead of being silently resolved. A merged state must
also pass structural validation.

## Versioned design context

Architecture decisions, interfaces, contracts, and task-specific constraints
can be stored with the branch revision:

```text
context_add(
  project="demo",
  branch="main",
  scope_kind="project",
  scope_name="demo",
  title="Memory ownership",
  body="All returned buffers are owned by the caller."
)
```

Agents retrieve the context with `context_get`. Because the documents are pinned
to revisions, later merge and audit operations can determine which rules an
agent saw while it worked.

## MCP tools

The current server exposes tools in these groups:

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_render`, `program_validate`
- **Atomic editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Inspection:** `node_inspect`, `node_find`
- **Context:** `context_add`, `context_get`

See [`docs/mcp.md`](docs/mcp.md) for the complete tool contract.

## Development

Run the checks before submitting changes:

```bash
python -m compileall -q src tests
ruff check .
pytest --cov=weave_frontend --cov-report=term-missing
```

Read:

- [`AGENTS.md`](AGENTS.md) for repository invariants;
- [`CONTRIBUTING.md`](CONTRIBUTING.md) for commit and pull request rules;
- [`docs/mcp.md`](docs/mcp.md) for MCP details;
- [`docs/architecture.md`](docs/architecture.md) for the broader design.

## Current limitations

- grammar help is derived from examples, not yet from a formal machine-readable
  grammar registry;
- full semantic validation requires a configured `weavec2` binary;
- the database currently stores complete immutable snapshots for simplicity;
- merge is intentionally conservative;
- build, run, test, artifact, and package-management tools are future work;
- the MCP and typed AST prototypes still coexist while the architecture settles.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
