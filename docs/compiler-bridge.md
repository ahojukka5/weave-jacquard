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
native executable + compiler manifest + diagnostics
```

Internally `weavec build` performs surface lowering, WIR generation, LLVM IR
emission, object generation, private target-runtime selection, and linking.
Those implementation phases are not part of the `weave_frontend` contract.

## Three representations

### Stored tree

The database representation is authoritative for agent editing. Every list and
atom has a stable `n_*` identity. Revisions are immutable and branches point to
revision IDs.

### Annotated agent view

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

### Canonical compiler view

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
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

An explicit target may be added:

```text
weavec build program.weave \
  -o program \
  --target x86_64-unknown-linux-musl \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

`weave_frontend` does not invoke `--frontend`, `--backend`, LLVM tools, a target
linker, or a runtime archive during a native build. Those remain private compiler
implementation details. The low-level compiler modes continue to be useful for
validation, bootstrap work, and compiler development.

## Private runtime boundary

The `weavec` product package contains its target runtime under a private path:

```text
bin/weavec
lib/weavec/<target>/libweave-runtime.a
```

`weavec build` discovers that resource relative to its own executable. A caller
never names the runtime. Source checkouts may use a compiler-development fallback,
but that path is also resolved by the compiler rather than `weave_frontend`.

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

The content-derived artifact layout is:

```text
.weave-build/
└── <build-id>/
    ├── program.weave
    ├── program.weave.map.json
    ├── compiler-manifest.json
    ├── compiler-diagnostics.json
    ├── diagnostics.json
    ├── manifest.json
    └── program
```

`compiler-diagnostics.json` is the raw versioned compiler document.
`diagnostics.json` is the validated bridge document with database-node mappings.
The executable exists only after a successful compiler build and a valid
machine-readable compiler response.

## Frontend build manifest

`weave-frontend-build-manifest-v1` records:

- build ID and status;
- project and branch used for the request;
- pinned revision ID and immutable revision root hash;
- document and canonical source hash;
- compiler path and SHA-256;
- compiler diagnostics protocol validity;
- requested target;
- normalized public compiler command and return code;
- relative artifact names and SHA-256 values.

Build-local paths in valid compiler JSON documents are normalized relative to
the final artifact directory before publication. Invalid raw diagnostics are
preserved byte-for-byte for investigation rather than reparsed during publishing.

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

## Mapped diagnostics

The compiler emits `weavec-diagnostics-v1`. The bridge validates the complete
outer document and every diagnostic entry before trusting it. The resulting
`weave-build-diagnostics-v1` contains:

```json
{
  "format": "weave-build-diagnostics-v1",
  "returncode": 11,
  "timed_out": false,
  "stdout": "",
  "stderr": "weavec: error: unknown expression operator: unknown_form\n",
  "compiler": {
    "format": "weavec-diagnostics-v1",
    "status": "failed",
    "phase": "backend",
    "exit_code": 11,
    "raw_exit_code": 1
  },
  "protocol_valid": true,
  "protocol_errors": [],
  "entries": [
    {
      "code": "backend.unknown-expression-operator",
      "severity": "error",
      "phase": "backend",
      "message": "unknown expression operator: unknown_form",
      "source": "program.weave",
      "compiler_source": "program.weave",
      "span_origin": "inferred-unique-token",
      "span": {
        "start_byte": 109,
        "end_byte": 121,
        "start_line": 6,
        "start_column": 18,
        "end_line": 6,
        "end_column": 30
      },
      "node_id": "n_..."
    }
  ]
}
```

A compiler source span is mapped only when its source identifies the generated
canonical `program.weave`. The smallest containing node is selected. Spanless or
non-canonical diagnostics remain valid entries with `node_id: null`.

`span_origin` is retained unchanged. Consumers can therefore distinguish exact
compiler-preflight spans from uniquely inferred token spans. Ambiguous compiler
locations remain unmapped rather than guessed.

Missing, malformed, unsupported, or internally inconsistent compiler diagnostics
produce a structured `bridge.invalid-compiler-diagnostics` entry. A process
launch error and timeout use their own bridge codes. Such protocol failures never
publish an executable, even if an untrusted compiler process returned zero.

## Failure and publication semantics

- A failed render or compiler invocation does not mutate program state.
- The final executable is absent on compiler or protocol failure.
- Every build refers to one immutable revision.
- Build files are created in a temporary sibling directory.
- The complete directory is published with an atomic rename.
- Successful identical builds are reused.
- Compilation and execution are separate operations.
- Raw malformed compiler output is retained as an artifact for debugging.

## Implementation status

Completed:

1. deterministic canonical rendering with per-node spans;
2. `weave-node-map-v1` serialization and source hash;
3. exact revision ownership validation and branch-head pinning;
4. one public `weavec build` invocation;
5. content-derived build IDs and successful-build reuse;
6. atomic artifact-directory publication;
7. CLI commands `build` and `get`;
8. MCP tools `program_build` and `build_get`;
9. versioned compiler diagnostics validation;
10. compiler source-span mapping to stable node IDs;
11. failure isolation for missing and malformed compiler protocol output.

Remaining refinements:

1. explicit source-location propagation through WIR to replace inferred backend
   token locations where possible;
2. optional richer compiler/toolchain identity and target metadata;
3. separately sandboxed `program_run`.
