# Compiler bridge: database revision to verified executable

## Purpose

`weave_frontend` owns immutable revisions, stable node identities, canonical
source materialization, and build provenance. `weavec` owns the language and
the complete native toolchain.

```text
immutable database revision
    ↓
ordered canonical sources + node maps
    ↓ weavec build
validated compiler manifest + validated diagnostics + executable
    ↓
verified immutable artifact directory
```

Agent annotations, LLVM phases, linker selection, and private runtime details
remain hidden from callers.

## Revision and source selection

A request supplies either a primary document plus ordered additional documents,
or a revisioned named target containing the same information.

The branch is resolved once. Target metadata and every selected source are read
from that exact immutable revision. An explicit revision must belong to the same
project. Building never creates a source revision or advances a branch.

Compiler input order is always the primary document followed by additional
documents in caller or target order. The bridge does not sort or silently add
project documents. Duplicate and missing names fail before compiler startup.

## Canonical sources and node maps

Each selected document is rendered without agent annotations. A matching
`weave-node-map-v1` records the database document, pinned revision,
canonical-source SHA-256, UTF-8 byte spans, line and column spans, and stable
node IDs.

Materialized filenames are deterministic and indexed:

```text
sources/000-main.weave
sources/001-library.weave
source-maps/000-main.weave.map.json
source-maps/001-library.weave.map.json
```

## Public compiler invocation

```text
weavec build \
  sources/000-main.weave \
  sources/001-library.weave \
  -o program \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

An explicit target is appended with `--target`. The bridge never invokes LLVM,
`--backend`, a linker, or a runtime archive. Target validation uses the same
ordered canonical sources but invokes `weavec --frontend`.

## Compiler manifest contract

`weavec-build-manifest-v1` is a required capability contract. The bridge
validates:

- object root and exact format;
- status and non-empty phase;
- `succeeded` implies `complete`;
- status agrees with process and diagnostics status;
- an explicitly requested target matches exactly;
- ordered source paths match every materialized input;
- output resolves to the requested temporary executable;
- compiler, runtime, code generator, and linker are non-empty strings;
- relative manifest paths cannot escape the build directory.

A missing, malformed, unsupported, or inconsistent compiler manifest produces
`bridge.invalid-compiler-manifest`, preserves raw evidence when available, and
withholds the executable even if the process returned zero.

When no target was explicitly requested, frontend provenance records
`target: native`, while `compiler_target` records the validated effective target
reported by `weavec`.

## Diagnostics contract and mapping

The complete `weavec-diagnostics-v1` document is validated before any entry is
trusted. Successful diagnostics require `phase: complete`, zero raw and public
exit codes, and no entries. Failed diagnostics require a nonzero raw exit code
and at least one error entry using a published span origin.

For each valid diagnostic the bridge identifies the exact canonical source,
selects its node map, verifies the byte span, selects the smallest containing
stable node, and adds the original database document and node ID. Spanless,
ambiguous, generated-WIR, and other non-canonical locations remain valid but
unmapped.

## Frontend build manifest

`weave-frontend-build-manifest-v2` records:

- build ID, status, and `weave-build-key-v4`;
- project, requested branch, pinned revision, and revision root hash;
- complete ordered document and source records;
- compiler path and binary SHA-256;
- requested target and validated effective compiler target;
- normalized compiler command and return code;
- compiler-manifest and diagnostics protocol validity;
- relative artifact references and SHA-256 values.

Single-document consumers may use `artifacts.source` and `artifacts.node_map`.
Multi-document consumers use `artifacts.sources` and `artifacts.node_maps`.

## Artifact verification

`build_get` and cache admission verify the frontend manifest before resolving
any artifact path:

- build IDs contain exactly 32 lowercase hexadecimal characters;
- the manifest build ID matches its directory name;
- every artifact reference is a non-empty relative path;
- resolved paths remain under the artifact directory, including through symlinks;
- artifact references and hash keys match exactly;
- every referenced object is a regular file;
- every hash is lowercase SHA-256 and matches current bytes.

Public inspection raises a structured error for malformed or corrupt stored
builds. Cache admission treats the same condition as a cache miss and rebuilds.

## Build identity and cache

`weave-build-key-v4` includes the bridge contract version, immutable revision
root hash and ID, ordered document/source-hash records, compiler binary hash,
and requested target. Changing source order, compiler binary, revision, or
target changes the build ID. Branch names are provenance rather than cache
identity.

A cache hit additionally requires a succeeded frontend manifest, return code
zero, valid compiler protocols, canonical required artifact names, and a
complete source/map set.

## Concurrent publication

Builds are prepared in temporary sibling directories and fully verified before
publication. Publication takes a POSIX advisory lock scoped to the build ID:

- an existing verified successful build wins and the candidate is discarded;
- failed or corrupt existing directories are moved aside;
- the verified candidate is installed with an atomic rename;
- the previous directory is restored if installation fails;
- temporary and quarantined directories are cleaned on every terminal path.

Two successful concurrent builds therefore converge on one verified result, and
a failed or incomplete late build cannot erase a successful result.

## Artifact layout

```text
.weave-build/<build-id>/
├── sources/
├── source-maps/
├── compiler-manifest.json
├── compiler-diagnostics.json
├── diagnostics.json
├── manifest.json
└── program                 successful builds only
```

Raw malformed compiler protocol files remain available as evidence when they
were produced. Failed builds never retain an executable or become cache hits.

## MCP and CLI

```text
program_build(...)
→ build_get(build_id)
```

```text
build_target_set(...)
→ build_target_validate(...)
→ build_target_build(...)
→ build_get(build_id)
```

```bash
weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application
weave-build --db weave.db get <build-id>
```

## Remaining work

- propagate exact surface locations through WIR where backend diagnostics still
  rely on conservative inference;
- expose richer compiler and target capability metadata;
- add separately sandboxed program execution.
