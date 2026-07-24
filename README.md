# weave_frontend

`weave_frontend` is an experimental **agent-native programming frontend** for
Weave. Instead of asking a language model to maintain a large text file, an
agent discovers, inspects, and mutates a versioned program tree through small,
validated operations.

The repository contains two related prototypes:

- the original typed AST workspace, which demonstrates validation, immutable
  revisions, branches, context, and semantic merge;
- `weave-mcp`, a grammar-neutral S-expression workspace exposed through the
  Model Context Protocol.

The MCP write API is deliberately atomic. An agent creates one form, atom, move,
wrap, or deletion per call rather than emitting a deeply nested JSON subtree.
Larger local subtrees may be returned for inspection.

## Install and test

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m compileall -q src tests
ruff check .
pytest
```

## Run weave-mcp

Place a `weavec2` checkout next to this repository, build it, and configure the
server:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVEC2_SOURCE_ROOT="../weavec2"
export WEAVEC2_BIN="../weavec2/build/weavec2"
weave-mcp
```

The default transport is MCP stdio. Configure an MCP client to execute the
`weave-mcp` command with the environment variables above.

The core agent workflow is:

```text
project_initialize
→ program_create
→ grammar_help
→ node_create_form / node_add_atom
→ node_inspect
→ program_validate
→ branch_merge
```

Writes are intentionally atomic. The agent creates one form or atom per tool
call and receives stable `n_*` node IDs immediately. `program_render` can return
an annotated view such as:

```lisp
(@n_a1b2 (program
  (@n_c3d4 (name "demo"))
  (@n_e5f6 (version "0.1"))))
```

The metadata is an agent view; canonical source omits the wrappers before being
passed to `weavec2`.

`grammar_help` does not maintain a second handwritten Weave grammar. It indexes
examples from `weavec2/test/correctness/surface`, reports observed arities and
parents, and links each example to its source file. `program_validate` then
invokes `weavec2 --frontend` as the normative check.

See [`docs/mcp.md`](docs/mcp.md) for tool details and
[`docs/architecture.md`](docs/architecture.md) for the broader design.
Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting changes.

## Typed AST example

The earlier typed workspace remains available:

```python
from weave_frontend import Workspace

with Workspace("demo.db") as workspace:
    workspace.initialize("demo")
    workspace.create_module("demo", "main", "app")
    workspace.upsert_function(
        "demo",
        "main",
        "app",
        {
            "kind": "fn",
            "name": "answer",
            "params": [],
            "returns": "i32",
            "body": [
                {
                    "kind": "return",
                    "value": {"kind": "const", "type": "i32", "value": 42},
                }
            ],
        },
    )
    print(workspace.render("demo", "main", "app"))
```
