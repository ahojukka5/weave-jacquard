# Compiler bridge: database revision to executable

## Purpose

`weave_frontend` owns a versioned program tree with stable node identities.
`weavec` owns the Weave language, surface validation, lowering, and code
generation. The bridge between them must preserve those responsibilities instead
of making agent metadata part of the language.

The target pipeline is:

```text
immutable database revision
        ↓
canonical surface Weave + node source map
        ↓  weavec --frontend
WIR
        ↓  weavec --backend
LLVM IR
        ↓  clang + Weave runtime
native executable
```

## Three representations

### 1. Stored tree

The database representation is authoritative for agent editing. Every list and
atom has a stable `n_*` identity. Revisions are immutable and branches point to
revision IDs.

### 2. Annotated agent view

The existing annotated syntax is a transport and inspection format:

```lisp
(@n_a1b2
  (fn main
    (@n_c3d4 (params))
    (@n_e5f6 (returns i32))
    (@n_a7b8 (do (return (const_i32 42))))))
```

`weave_frontend` may render and parse this form to preserve identities during
agent-facing round trips. It is not canonical Weave source and must never be
required by `weavec`.

### 3. Canonical compiler view

The same tree is rendered without annotations:

```lisp
(fn main
  (params)
  (returns i32)
  (do (return (const_i32 42))))
```

Only this representation is passed to `weavec`. The compiler therefore remains
usable independently of the database and MCP server.

## Source-map contract

Removing `@n_*` wrappers means compiler diagnostics no longer carry database
node identities directly. `weave_frontend` must therefore produce two outputs in
one deterministic render operation:

```text
program.weave
program.weave.map.json
```

The map records at least:

```json
{
  "format": "weave-node-map-v1",
  "source_sha256": "...",
  "revision_id": "...",
  "document": "main.weave",
  "nodes": [
    {
      "node_id": "n_a7b8",
      "start_byte": 47,
      "end_byte": 83,
      "start_line": 4,
      "start_column": 3,
      "end_line": 4,
      "end_column": 39
    }
  ]
}
```

Offsets are UTF-8 byte offsets with an exclusive end. When a diagnostic covers
several nested nodes, the bridge selects the smallest mapped node containing the
diagnostic span and may also return its ancestor chain.

The initial bridge can map surface parse and validation diagnostics. Later
`weavec` may propagate source locations through WIR and LLVM debug metadata so
backend and runtime diagnostics retain the same identity chain.

## Compiler invocation contract

The bridge invokes explicit compiler modes only:

```text
weavec --frontend program.wir program.weave
weavec --backend program.wir program.ll
clang program.ll /path/to/libweave-runtime.a -o program
```

The implicit backend spelling is not supported.

For reliable automation, `weavec` should add machine-readable diagnostics:

```text
weavec --diagnostics-json diagnostics.json --frontend program.wir program.weave
weavec --diagnostics-json diagnostics.json --backend program.wir program.ll
```

Each diagnostic should include a stable code, severity, message, phase, source
path, and UTF-8 byte or line/column span. `weave_frontend` maps that span back to
node IDs using the sidecar map.

## Runtime boundary

Producing LLVM IR is not the same as producing a complete program. The `weavec`
release must expose a versioned runtime link contract, preferably:

```text
lib/libweave-runtime.a
include/weave/runtime.h
```

`weave_frontend` should link the runtime archive unconditionally. Static archive
members that are not referenced are not pulled into the executable, while
programs using contracts or runtime helpers remain supported. The runtime
version and checksum belong in the build manifest.

Until the runtime archive is published, the bridge may accept an explicit
`WEAVEC_RUNTIME` path. A source-tree-relative runtime path is a development
fallback, not the production contract.

## Revision-pinned build operation

A build request identifies an immutable input:

```text
project
branch or exact revision_id
document
compiler/toolchain selection
target
optimization profile
```

The branch head is resolved to a revision before rendering. All later steps use
that exact revision even if the branch advances during the build.

Suggested artifact layout:

```text
.weave-build/
└── <project>/
    └── <revision-id>/
        └── <document>/
            └── <target>/
                ├── program.weave
                ├── program.weave.map.json
                ├── program.wir
                ├── program.ll
                ├── program
                ├── diagnostics.json
                └── manifest.json
```

The manifest records:

- project, branch, revision, and document;
- canonical source hash;
- compiler path, version, and binary hash;
- runtime path, version, and hash;
- target and flags;
- every command and exit status;
- artifact paths and hashes;
- timestamps and final status.

## Cache key

A build is reusable only when this key is unchanged:

```text
revision content hash
+ document identity
+ weavec binary hash/version
+ runtime hash/version
+ target triple
+ optimization and compiler flags
```

Branch names are not cache keys because branch heads move.

## MCP surface

The current tools remain:

- `program_render(annotated=true)` for agents;
- `program_render(annotated=false)` for canonical source;
- `program_validate` for structural and compiler validation.

The bridge should add:

### `program_build`

Pins the revision, renders canonical source and source map, runs the compiler and
linker, stores artifacts, and returns a build ID plus mapped diagnostics.

### `build_get`

Returns manifest, status, diagnostics, and artifact metadata for a build ID.

### `program_run`

A later operation that executes an already built artifact under an explicit
sandbox and resource policy. Compilation and execution remain separate actions.

## Failure semantics

- A failed render, compiler phase, or link does not mutate program state.
- Partial files remain under the build ID for diagnostics but are never reported
  as a successful executable.
- Diagnostics are returned both in compiler coordinates and mapped node IDs.
- Building never advances a branch or creates a source revision.
- Execution is never implicit in `program_build`.

## Implementation order

1. Add deterministic canonical rendering with node spans.
2. Add `weave-node-map-v1` serialization and tests.
3. Add a revision-pinned local build service that produces `.weave`, WIR, and
   LLVM IR.
4. Publish a versioned runtime archive from `weavec` and add native linking.
5. Add `program_build` and `build_get` MCP tools.
6. Add JSON diagnostics to `weavec` and map them to node IDs.
7. Add content-addressed build caching.
8. Add separately sandboxed `program_run`.
