# Compiler bridge: database revision to executable

## Purpose

`weave_frontend` owns immutable revisions, stable node identities, canonical
source materialization, and build provenance. `weavec` owns the language and
the complete native toolchain.

The bridge converts one ordered source set from one exact database revision into
a native executable:

```text
immutable revision
    ↓
ordered canonical sources + one node map per source
    ↓  weavec build
executable + compiler manifest + mapped diagnostics
```

Agent annotations, LLVM phases, linker selection, and the private runtime remain
hidden from callers.

## Revision and source selection

A request supplies either:

- a primary `document` plus optional ordered `additional_documents`; or
- a revisioned named build target containing that same information.

A branch is resolved once before rendering:

```text
project + branch
    ↓ resolve once
revision ID + revision root hash
    ↓
read target metadata and every source from that revision
```

An explicit revision ID bypasses branch-head resolution but must belong to the
same project. A branch may advance during compilation without affecting the
running build. Building never creates a source revision or advances a branch.

The compiler input order is always:

```text
primary document
additional document 0
additional document 1
...
```

The bridge does not sort the list or silently include all project documents.
Duplicate names and missing revision documents are rejected before compiler
startup.

## Canonical source and node maps

Each selected document is independently rendered without agent `@n_*`
annotations. A matching `weave-node-map-v1` records:

- the database document name;
- pinned revision ID;
- canonical source SHA-256;
- UTF-8 byte spans with exclusive ends;
- one-based line and column spans;
- stable node IDs.

Materialized filenames are deterministic and indexed so equal basenames cannot
collide:

```text
sources/000-main.weave
sources/001-library.weave
source-maps/000-main.weave.map.json
source-maps/001-library.weave.map.json
```

The database document names remain in the frontend manifest and node maps. The
indexed names are build-local compiler inputs only.

## Public compiler invocation

The bridge invokes one public native-build contract:

```text
weavec build \
  sources/000-main.weave \
  sources/001-library.weave \
  -o program \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

An optional compiler target is appended with `--target`.

The bridge never invokes LLVM, `--backend`, a platform linker, or a runtime
archive. `weavec` owns surface lowering, WIR, LLVM IR, object generation,
runtime selection, target linking, and executable publication.

Target validation uses the same ordered canonical source representation but
calls:

```text
weavec --frontend output.wir source0.weave source1.weave ...
```

## Artifact layout

```text
.weave-build/<build-id>/
├── sources/
├── source-maps/
├── compiler-manifest.json
├── compiler-diagnostics.json
├── diagnostics.json
├── manifest.json
└── program
```

The executable is retained only when the compiler returns success and produces
a valid `weavec-diagnostics-v1` response.

## Frontend manifest

`weave-frontend-build-manifest-v2` records:

- build ID, status, and build-key contract;
- project, requested branch, pinned revision ID, and revision root hash;
- primary document and complete ordered document list;
- one source record per document with canonical hash and node-map path;
- compiler path and SHA-256;
- target, normalized compiler command, and return code;
- compiler diagnostics protocol validity;
- relative artifact names and SHA-256 values.

For single-document compatibility, `artifacts.source` and
`artifacts.node_map` identify the primary source. Multi-document consumers use
`artifacts.sources` and `artifacts.node_maps`.

`build_get` adds absolute `artifact_paths` for stored artifacts and does not
require the compiler to remain installed. Manifest path containment and cached
artifact hash verification are tracked as required hardening in issue #17.

## Build identity and cache

`weave-build-key-v3` includes:

```text
bridge contract version
+ immutable revision root hash and revision ID
+ ordered (document name, canonical source hash) records
+ compiler binary hash
+ target
```

Changing source order, compiler binary, revision, or target changes the build
ID. Branch names are provenance rather than cache identity.

Only a successful build with a valid compiler-diagnostics artifact and complete
source/map artifacts is eligible for reuse. Full artifact-integrity admission
and non-destructive concurrent publication are not yet complete; see issue #17.

## Diagnostics mapping

The bridge validates the complete compiler diagnostics document before trusting
an entry. For each diagnostic it:

1. identifies the exact materialized source named by the compiler;
2. selects that source's node map;
3. checks that the byte span fits within the canonical source;
4. selects the smallest stable node containing the span;
5. adds the original database `document` and `node_id`.

A mapped secondary-source diagnostic therefore retains both identities:

```json
{
  "source": "001-library.weave",
  "compiler_source": "001-library.weave",
  "document": "library.weave",
  "node_id": "n_..."
}
```

Spanless, ambiguous, generated-WIR, and other non-canonical locations remain
valid but unmapped. The bridge does not guess.

Missing, malformed, unsupported, or internally inconsistent compiler output
creates a structured bridge error and prevents executable publication even if
the compiler process returned zero. Raw compiler output remains available for
investigation.

## MCP and CLI

Ad hoc MCP build:

```text
program_build(
  project="demo",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"],
  branch="main"
)
→ build_get(build_id)
```

Revisioned target flow:

```text
build_target_set(...)
→ build_target_validate(...)
→ build_target_build(...)
→ build_get(build_id)
```

CLI equivalents:

```bash
weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application

weave-build --db weave.db build demo main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db get <build-id>
```

## Failure and publication semantics

- Rendering or compiler failure never mutates a database revision.
- Missing or duplicate selected documents fail before compiler startup.
- Compiler or diagnostics-protocol failure publishes diagnostics but no
  executable.
- Build work occurs in a temporary sibling directory.
- A completed artifact directory is installed with a rename.
- Non-destructive publication under concurrent identical builds remains tracked
  in issue #17.
- Compilation is separate from future sandboxed execution.

## Remaining work

- issue #14: remove the typed-AST prototype from the production workspace path;
- issue #17: verify cached artifact hashes, enforce path containment, and make
  concurrent publication non-destructive;
- propagate exact surface locations through WIR where backend diagnostics still
  rely on conservative inference;
- expose richer compiler and target capability metadata;
- add separately sandboxed program execution.
