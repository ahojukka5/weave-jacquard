# weave_frontend

`weave_frontend` is an experimental **agent-native programming environment**
for Weave. Coding agents edit a versioned S-expression tree through small MCP
tool calls instead of repeatedly generating and replacing complete source files.

The primary executable is **`weave-mcp`**. It provides:

- atomic form and atom edits;
- stable semantic node IDs;
- immutable revision history;
- parallel branches and structural merge;
- grammar help derived from the canonical compiler corpus;
- authoritative validation through `weavec --frontend`;
- deterministic canonical `.weave` rendering.

> The model decides what program to build. The environment owns tree structure,
> identity, history, and transactional safety.

## Status

This repository is a runnable prototype, not a replacement compiler. The
user-facing compiler is [`weavec`](https://github.com/ahojukka5/weavec). This
project uses that compiler as the language authority while experimenting with a
more reliable editing interface for coding agents.

The repository contains two related prototypes:

1. **`weave-mcp`** — the primary grammar-neutral MCP server for atomic
   S-expression construction.
2. **Typed AST prototype** — the earlier frontend used to prove immutable
   revisions, validation, context, and semantic merge.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Install `weavec` on `PATH`, or point the MCP server to a compiler binary and an
optional source checkout:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVEC_SOURCE_ROOT="../weavec"
export WEAVEC_BIN="../weavec/build/weavec"
```

`WEAVEC_BIN` is optional when `weavec` is already available on `PATH`.
`WEAVEC_SOURCE_ROOT` is used by grammar discovery to scan the compiler's surface
fixture corpus.

Run the stdio MCP server:

```bash
weave-mcp
```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `WEAVE_DB_PATH` | SQLite program database | `weave.db` |
| `WEAVEC_SOURCE_ROOT` | `weavec` checkout used by grammar help | unset |
| `WEAVEC_BIN` | `weavec` executable used for validation | `weavec` from `PATH` |

Tree editing works without the compiler. Grammar examples require the source
checkout, and authoritative completed-program validation requires the binary.

## MCP client configuration

A typical stdio client configuration is:

```json
{
  "mcpServers": {
    "weave": {
      "command": "/path/to/venv/bin/weave-mcp",
      "env": {
        "WEAVE_DB_PATH": "/path/to/project/weave.db",
        "WEAVEC_SOURCE_ROOT": "/path/to/weavec",
        "WEAVEC_BIN": "/path/to/weavec/build/weavec"
      }
    }
  }
}
```

The exact outer format depends on the MCP client. The command and environment
variables are the relevant contract.

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

Agents should call `grammar_help` before using an unfamiliar form and should
prefer atomic writes over bulk `program_import`.

## Atomic construction example

The following program returns 42:

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

Construct it one semantic operation at a time:

```text
project_initialize(project="demo")
program_create(
  project="demo",
  branch="main",
  document="main",
  program_name="answer"
)
```

Use the returned root ID as `program_id`, then create the entry and function
forms:

```text
node_create_form(parent_id=program_id, head="entry", ...) → entry_id
node_add_atom(parent_id=entry_id, kind="symbol", value="main", ...)

node_create_form(parent_id=program_id, head="fn", ...) → fn_id
node_add_atom(parent_id=fn_id, kind="symbol", value="main", ...)
node_create_form(parent_id=fn_id, head="params", ...)
node_create_form(parent_id=fn_id, head="returns", ...) → returns_id
node_add_atom(parent_id=returns_id, kind="symbol", value="i32", ...)
node_create_form(parent_id=fn_id, head="do", ...) → do_id

node_create_form(parent_id=do_id, head="return", ...) → return_id
node_create_form(parent_id=return_id, head="const_i32", ...) → const_id
node_add_atom(parent_id=const_id, kind="integer", value=42, ...)
```

Inspect and validate the result:

```text
node_inspect(node_id=fn_id, depth=6, ...)
program_validate(project="demo", branch="main", document="main")
```

Every successful mutation creates a new immutable revision and returns stable
node IDs for subsequent calls.

## Grammar discovery and validation

`grammar_help` searches:

```text
$WEAVEC_SOURCE_ROOT/test/correctness/surface
```

It reports observed forms, parent forms, arities, examples, and fixture paths.
This is construction guidance rather than a duplicate normative grammar.

The final language check is:

```text
program_validate → weavec --frontend output.wir input.weave
```

A future machine-readable grammar registry in `weavec` can replace corpus
inference without changing the MCP API.

## Stable node IDs

Every list and atom has an internal stable ID such as `n_...`.

- creating a node assigns a new ID;
- editing an atom preserves its ID;
- moving a node preserves its ID;
- wrapping creates a new wrapper ID and preserves the wrapped node ID;
- deleting removes the node and its subtree;
- branches preserve IDs inherited from their base revision;
- merge compares semantic identity instead of source lines.

Canonical rendering omits IDs. Agent-facing annotated rendering exposes them.

## Parallel agents and merge

Each agent should work on a database branch:

```text
branch_create(project="demo", branch="agent/foo")
branch_create(project="demo", branch="agent/bar")
```

Merge uses stable node identities and a three-way tree comparison. Independent
changes are retained; incompatible edits are reported as conflicts. A merged
state must still pass structural and compiler validation.

## MCP tools

The current server exposes:

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_render`, `program_validate`
- **Atomic editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Inspection:** `node_inspect`, `node_find`
- **Context:** `context_add`, `context_get`

See [`docs/mcp.md`](docs/mcp.md) for the tool contract and
[`docs/architecture.md`](docs/architecture.md) for the broader design.

## Development

```bash
python -m compileall -q src tests
ruff check .
pytest --cov=weave_frontend --cov-report=term-missing
```

Repository invariants and contribution rules are documented in
[`AGENTS.md`](AGENTS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Current limitations

- grammar help is derived from examples rather than a formal registry;
- full semantic validation requires `weavec`;
- immutable database snapshots are intentionally simple rather than compact;
- merge is conservative;
- build, run, package, and artifact tools remain future work;
- the MCP and typed AST prototypes still coexist.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
