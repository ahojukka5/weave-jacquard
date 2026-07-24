# weave_frontend

`weave_frontend` is an experimental **agent-native programming frontend** for
Weave. Instead of asking a language model to maintain a large text file, an
agent discovers, inspects, and mutates a typed program tree through small,
validated operations.

The repository is a runnable Python prototype for the architectural idea. It is
not yet a replacement for `weavefront` or `weavec2`.

## Why

Small and inexpensive coding models often understand an algorithm but lose
reliability when they must also maintain punctuation, source locations, scope,
and a large textual context. This prototype moves the mechanical work into the
programming environment:

- every AST mutation is grammar-checked before commit;
- explicit syntax holes make incomplete drafts structurally valid;
- SQLite stores immutable revisions and branch heads;
- functions and modules are found through semantic identities, not line numbers;
- multiple agents work on independent branches;
- three-way merge happens at module and symbol granularity;
- merged programs are type-checked as a whole;
- contracts and design documents are stored as versioned context;
- canonical Weave text is a deterministic view of the database state.

## Current prototype

The first version supports:

- modules and imports;
- scalar types `i32`, `i64`, `bool`, and `void`;
- functions, parameters, locals, calls, binary expressions, `if`, `while`, and
  `return`;
- immediate structural validation;
- semantic validation and symbol resolution;
- stable AST node IDs;
- immutable revision history, checkout, and branches;
- symbol-level three-way merge;
- project-, module-, and symbol-scoped design context;
- deterministic surface-Weave rendering.

## Install and test

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
```

## Minimal example

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

## Agent workflow

A draft function is born with a syntactically valid hole:

```python
result = workspace.create_function(
    "demo",
    "agent/factorial",
    "app",
    "factorial",
    params=[{"name": "n", "type": "i32"}],
    returns="i32",
)
```

The agent inserts valid statement subtrees before the hole, replaces the hole
with the final statement, and calls `finalize_function`. A malformed mutation is
rejected atomically and does not advance the branch revision.

See [`docs/architecture.md`](docs/architecture.md) for the complete design.
