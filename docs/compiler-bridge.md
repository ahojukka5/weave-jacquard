# Compiler bridge: database revision to executable

## Purpose

`weave_frontend` owns immutable program revisions and stable `n_*` node
identities. `weavec` owns the language and the complete native toolchain. The
bridge converts one ordered set of database documents from one exact revision
into a native executable without exposing agent annotations, LLVM phases, the
linker, or the private runtime to callers.

```text
immutable database revision
        ↓
ordered canonical sources + one node map per source
        ↓  weavec build
native executable + manifests + mapped diagnostics
```

## Stored, agent, and compiler views

The database tree is authoritative for editing. Agent-facing rendering may show
stable-ID wrappers such as:

```lisp
(@n_function
  (fn main
    (@n_params (params))
    (@n_returns (returns i32))))
```

Those wrappers are transport metadata, not Weave syntax. Each selected document
is rendered independently into canonical source with no `@n_*` wrappers:

```lisp
(fn main
  (params)
  (returns i32))
```

`weavec` therefore remains independent of the database and MCP protocol.

## Ordered document set

A build request identifies a primary `document` and optionally an ordered
`additional_documents` list. The compiler receives:

```text
document
additional_documents[0]
additional_documents[1]
...
```

The bridge does not silently add every project document and does not sort the
list. Input order is explicit, deterministic, and part of the build identity.
Duplicate names are rejected. Every selected document must exist in the same
pinned revision.

The single-document API remains the special case where
`additional_documents` is omitted.

## Revision pinning

A branch request is resolved to one immutable revision before rendering:

```text
project + branch
        ↓ resolve once
revision_id + revision root hash
        ↓
read every selected document from that revision
```

If the branch advances during compilation, the running build is unaffected.
Building never creates a source revision or advances a branch.

## Canonical source and node maps

Each selected document is rendered with its own `weave-node-map-v1` document.
The map records:

- original database document name;
- pinned revision ID;
- canonical-source SHA-256;
- UTF-8 byte spans with exclusive ends;
- one-based line and column spans;
- stable `n_*` node identities.

Materialized filenames are deterministic and indexed to avoid basename
collisions:

```text
sources/000-main.weave
sources/001-library.weave
source-maps/000-main.weave.map.json
source-maps/001-library.weave.map.json
```

The database document names remain in the build manifest and node maps. The
indexed filenames are build-local compiler inputs only.

## Public compiler invocation

The bridge invokes one public compiler contract:

```text
weavec build \
  sources/000-main.weave \
  sources/001-library.weave \
  -o program \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

An optional target is appended with `--target`. The bridge never invokes LLVM,
`--backend`, a target linker, or a runtime archive during a native build.
`weavec` owns surface lowering, WIR, LLVM IR, object generation, private runtime
selection, target linking, and atomic executable publication.

## Artifact layout

```text
.weave-build/<build-id>/
├── sources/
│   ├── 000-main.weave
│   └── 001-library.weave
├── source-maps/
│   ├── 000-main.weave.map.json
│   └── 001-library.weave.map.json
├── compiler-manifest.json
├── compiler-diagnostics.json
├── diagnostics.json
├── manifest.json
└── program
```

The executable exists only after a successful compiler process and a valid
`weavec-diagnostics-v1` response.

## Frontend build manifest

`weave-frontend-build-manifest-v2` records:

- build ID, status, and `weave-build-key-v3` cache contract;
- project, requested branch, pinned revision ID, and revision root hash;
- primary document and the complete ordered document list;
- one source record per document with canonical source, node-map path, and hash;
- compiler path and SHA-256;
- compiler diagnostics protocol validity;
- target, normalized compiler command, and return code;
- relative artifact names and SHA-256 values.

For backward-compatible single-document consumers, `artifacts.source` and
`artifacts.node_map` still point to the primary source. New consumers should use
`artifacts.sources` and `artifacts.node_maps`.

`build_get` recursively expands string, list, and object artifact references into
absolute `artifact_paths` without requiring the compiler to remain installed.

## Cache identity

`weave-build-key-v3` includes:

```text
bridge contract version
+ immutable revision root hash and ID
+ ordered (document name, canonical source hash) records
+ weavec binary hash
+ target
```

Changing source order changes the build ID. Branch names are provenance rather
than cache identity. Only successful builds with a valid compiler diagnostics
artifact and complete source/map artifacts are reused.

## Multi-source diagnostics

The bridge validates the complete `weavec-diagnostics-v1` document before
trusting any entry. For every diagnostic:

1. identify which materialized canonical source the compiler named;
2. choose that source's node map;
3. verify the byte span is within that source;
4. select the smallest stable node containing the span;
5. add both the original database `document` and `node_id`.

A mapped entry therefore includes separate identities:

```json
{
  "source": "001-library.weave",
  "compiler_source": "001-library.weave",
  "document": "library.weave",
  "node_id": "n_..."
}
```

Spanless, ambiguous, generated-WIR, and other non-canonical locations remain
valid diagnostics with `document: null` and `node_id: null`; the bridge does not
guess. `span_origin` is preserved unchanged.

Missing, malformed, unsupported, or internally inconsistent compiler output
produces a structured bridge error and prevents executable publication, even if
an untrusted compiler process returned zero. Raw malformed diagnostics are kept
byte-for-byte for investigation.

## MCP and CLI

MCP:

```text
program_build(
  project,
  document,
  additional_documents=["library.weave", "platform.weave"],
  branch="main"
)
build_get(build_id)
```

CLI:

```text
weave-build --db weave.db build demo main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db get <build-id>
```

Each repeated `--source` preserves its command-line order.

## Failure and publication semantics

- Rendering or compiler failure never mutates the database revision.
- A missing selected document fails before starting the compiler.
- Duplicate selected documents are rejected.
- Compiler or protocol failure publishes diagnostics but no executable.
- Build files are prepared in a temporary sibling directory.
- The complete artifact directory is published with an atomic rename.
- Compilation remains separate from future sandboxed execution.

## Remaining refinements

- propagate exact surface locations explicitly through WIR where backend
  diagnostics currently rely on conservative inference;
- expose richer compiler/toolchain capability metadata;
- define persistent named build targets instead of requiring callers to repeat
  a long document order;
- implement separately sandboxed `program_run`.
