# Compiler bridge: database revision to executable

## Purpose

`weave_frontend` owns a versioned program tree with stable node identities.
`weavec` owns the Weave language and the complete native toolchain. The bridge
preserves those responsibilities instead of making agent metadata, LLVM phases,
or runtime selection part of the database service.

The implemented pipeline is:

```text
immutable database revision
        ↓
canonical surface Weave + node source map
        ↓  weavec build
native executable + compiler manifest
```

Internally `weavec build` performs surface lowering, WIR generation, LLVM IR
emission, object generation, private target-runtime selection, and linking.
Those implementation phases are not part of the `weave_frontend` contract.

## Three representations

### 1. Stored tree

The database representation is authoritative for agent editing. Every list and
atom has a stable `n_*` identity. Revisions are immutable and branches point to
revision IDs.

### 2. Annotated agent view

The annotated syntax is a transport and inspection format:

```lisp
(@n_a1b2
  (fn main
    (@n_c3d4 (params))
    (@n_e5f6 (returns i32))
    (@n_a7b8 (do (return (const_i32 42))))))
```

`weave_frontend` may render and parse this form to preserve identities during
agent-facing round trips. It is not canonical Weave source and is never passed
to `weavec`.

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

Canonical source and the sidecar map are produced by one deterministic render
operation:

```text
program.weave
program.weave.map.json
```

The implemented map format is:

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
nested nodes, the bridge selects the smallest mapped node containing the span.
The map is independently verifiable because it includes the canonical source
hash and pinned revision ID.

## Public compiler invocation

The bridge invokes one public compiler contract:

```text
weavec build program.weave \
  -o program \
  --manifest-json compiler-manifest.json
```

An explicit target may be added:

```text
weavec build program.weave \
  -o program \
  --target x86_64-unknown-linux-musl \
  --manifest-json compiler-manifest.json
```

`weave_frontend` does not invoke `--frontend`, `--backend`, LLVM tools, a target
linker, or a runtime archive during a native build. Those remain private compiler
implementation details. The low-level compiler modes continue to be useful for
validation, bootstrap work, and compiler development.

## Private runtime boundary

The `weavec` product package contains its target runtime under a private path such
as:

```text
bin/weavec
lib/weavec/<target>/libweave-runtime.a
```

`weavec build` discovers that resource relative to its own executable. A caller
never names the runtime. Source checkouts may use a compiler-development fallback,
but that path is also resolved by the compiler rather than `weave_frontend`.

This division permits target-specific runtimes, release checksums, and dead-code
elimination without exposing a second user-facing build API.

## Revision-pinned build operation

A request identifies:

```text
project
branch or exact revision_id
document
weavec selection
target
```

The branch head is resolved to an immutable revision before rendering. All later
steps use that exact revision even if the branch advances during compilation.
Building never advances a branch or creates a source revision.

The implemented artifact layout is content-derived:

```text
.weave-build/
└── <build-id>/
    ├── program.weave
    ├── program.weave.map.json
    ├── compiler-manifest.json
    ├── diagnostics.json
    ├── manifest.json
    └── program
```

The executable exists only after a successful compiler build. A failed build
keeps source, node map, diagnostics, and manifests but records no executable.

## Frontend build manifest

`weave-frontend-build-manifest-v1` records:

- build ID and status;
- project and branch used for the request;
- pinned revision ID and immutable revision root hash;
- document and canonical source hash;
- compiler path and SHA-256;
- requested target;
- normalized public compiler command and return code;
- relative artifact names and SHA-256 values.

Build-local paths in the compiler manifest are normalized relative to the final
artifact directory before publication, so the whole directory remains movable.

## Cache key

The current build ID includes:

```text
immutable revision root hash and ID
+ document identity
+ canonical source hash
+ weavec binary hash
+ target
```

Branch names are provenance, not cache identity, because branch heads move.
Successful identical requests are reused. Failed builds are not treated as cache
hits and may be rebuilt.

## MCP and CLI surface

The existing tools remain:

- `program_render(annotated=true)` for agents;
- `program_render(annotated=false)` for canonical source;
- `program_validate` for structural and compiler validation.

The build bridge adds:

### `program_build`

Pins the revision, renders canonical source and source map, invokes `weavec build`,
publishes the artifact directory atomically, and returns the build manifest plus
absolute artifact paths.

### `build_get`

Returns a stored manifest and artifact paths by build ID. Compiler availability
is not required merely to inspect an existing build.

The same API is exposed through:

```text
weave-build --db weave.db build <project> <document>
weave-build --db weave.db get <build-id>
```

### Future `program_run`

Execution remains a separate future operation with an explicit sandbox, resource
limits, and target policy. `program_build` never executes the produced program.

## Diagnostics

The first implementation stores:

```json
{
  "format": "weave-build-diagnostics-v1",
  "returncode": 1,
  "timed_out": false,
  "stdout": "...",
  "stderr": "...",
  "entries": []
}
```

The `entries` array is reserved for machine-readable compiler diagnostics. Once
`weavec` emits stable source spans, `weave_frontend` will map each span through
`weave-node-map-v1` to the smallest containing `n_*` node and optionally its
ancestor chain. Human-readable stderr remains preserved for compatibility.

## Failure and publication semantics

- A failed render or compiler invocation does not mutate program state.
- The final executable is absent on failure.
- Every build refers to one immutable revision.
- Build files are created in a temporary sibling directory.
- The complete directory is published with an atomic rename.
- Successful identical builds are reused.
- Compilation and execution are separate operations.

## Implementation status

Completed in the first bridge version:

1. deterministic canonical rendering with per-node spans;
2. `weave-node-map-v1` serialization and source hash;
3. exact revision ownership validation and branch-head pinning;
4. `weavec build` invocation only;
5. content-derived build IDs and successful-build reuse;
6. atomic artifact-directory publication;
7. CLI commands `build` and `get`;
8. MCP tools `program_build` and `build_get`;
9. tests for annotation stripping, node lookup, revision pinning, executable
   production, cache reuse, and failure isolation.

Remaining compiler-side extension:

1. versioned machine-readable source diagnostics from `weavec`;
2. diagnostic span mapping into node IDs;
3. optional richer compiler/toolchain identity and target metadata;
4. separately sandboxed `program_run`.
