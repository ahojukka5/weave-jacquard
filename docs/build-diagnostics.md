# Build diagnostic inspection

## Purpose

A build may run on a different machine from the MCP client. Absolute paths
returned by `build_get` are useful to local operators, but an agent must not
assume that it can open files on the server filesystem.

`build_diagnostics_page` exposes the mapped, retained diagnostic entries through
the public MCP protocol:

```text
build_diagnostics_page(
  build_id,
  start_index = 0,
  limit = 50
)
```

The tool is read-only. It does not invoke the compiler, mutate a revision, or
change a stored build.

## Verified admission

Before reading diagnostics, the tool calls the same verified build lookup as
`build_get`. The stored frontend manifest must pass its normal checks:

- supported manifest format and matching build ID;
- relative artifact paths contained below the build directory;
- exact agreement between artifact references and SHA-256 keys;
- regular-file checks for every artifact;
- current SHA-256 verification of every referenced artifact.

The mapped `diagnostics.json` must then contain a
`weave-build-diagnostics-v1` object whose `entries` field is an array of
objects. Corrupt, missing, or unsupported evidence is rejected rather than
returned partially.

## Pagination

`start_index` is a zero-based diagnostic index. It must be a non-negative
integer. `limit` must be between 1 and 200.

The response contains:

```text
build_id
status
revision_id
project
branch
document
documents
returncode
protocol_valid
protocol_error_count
compiler
compiler_manifest
compiler_manifest_protocol_valid
total_diagnostic_count
start_index
limit
returned_count
has_more
next_index
diagnostics
```

Each item in `diagnostics` is the exact mapped entry retained by the compiler
bridge, including its code, message, phase, canonical document, source span,
span origin, and stable `node_id` when mapping succeeded.

When `has_more` is true, pass `next_index` as the next `start_index`. A cursor at
or beyond the total count returns an empty terminal page. Builds and their
artifacts are immutable, so no branch-head stability check is needed between
pages.

## Bounded response contract

The tool deliberately does not return raw compiler `stdout` or `stderr`. Those
streams can be large and are retained in the verified diagnostics artifact for
operator investigation. The MCP response returns structured diagnostic entries
and compact compiler/protocol summaries only.

Protocol error details and raw malformed compiler documents likewise remain in
the retained build evidence. `protocol_error_count` reports whether protocol
errors exist without making the page unbounded.

## Compiler-guided repair

A normal repair loop is:

```text
program_build
→ build_diagnostics_page
→ inspect diagnostic.node_id
→ node_inspect
→ node_set_atom / another structural repair
→ program_validate or build_target_validate
→ program_build / build_target_build
```

A failed build does not advance a branch and does not publish an executable.
The failed build remains available by its content-derived build ID after later
revisions are repaired and built successfully.

When a diagnostic contains a stable `node_id`, repair that node rather than
searching by line number. Editing an atom or moving a node preserves its ID, so
the failed diagnostic and the corrective revision remain directly traceable.

## Relationship to `build_get`

Use `build_get` for verified provenance, revision identity, ordered sources,
compiler identity, target, artifact hashes, and local artifact paths. Use
`build_diagnostics_page` for remote-safe, bounded access to mapped compiler and
bridge diagnostics.
