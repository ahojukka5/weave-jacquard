# Structural resource limits

Jacquard rejects structural inputs that exceed explicit resource ceilings before
publishing an immutable revision or materializing compiler source.

## Current limits

The canonical values live in `weave_frontend.structural_limits`:

| Limit | Value | Boundary |
|---|---:|---|
| `MAX_SOURCE_BYTES` | 4 MiB | one imported S-expression source string |
| `MAX_TREE_DEPTH` | 512 | root-to-node structural depth |
| `MAX_TREE_NODES` | 100,000 | nodes in one document tree |
| `MAX_ATOM_VALUE_BYTES` | 1 MiB | one atom's canonical UTF-8 payload |
| `MAX_TREE_VALUE_BYTES` | 8 MiB | aggregate atom payload in one tree |
| `MAX_RENDERED_SOURCE_BYTES` | 16 MiB | one canonical or annotated rendering |

These are safety ceilings, not recommended program sizes. Agent workflows should
normally operate far below them through bounded local inspection and structural
edits.

## Imported source

`parse_source` first encodes the supplied string as UTF-8 and rejects inputs over
`MAX_SOURCE_BYTES` with `SOURCE_TOO_LARGE`.

During parsing it tracks every temporary parsed node and nesting depth. It rejects
excess with:

- `TREE_TOO_DEEP`;
- `TREE_TOO_LARGE`.

The final parsed tree still passes complete structural validation. The parser's
construction counters prevent deeply nested or extremely wide source from being
fully materialized before the normal tree validator runs.

## Tree validation

`validate_tree` uses an explicit stack rather than recursive traversal. It:

- requires the root itself to be an object;
- validates every node shape and value;
- rejects duplicate stable node IDs;
- enforces maximum depth and node count;
- enforces individual atom payload size;
- accumulates and bounds total atom payload bytes.

A non-object root now returns `INVALID_NODE`. It can no longer pass validation
because an empty recursive iterator visited no nodes.

The payload errors are:

- `ATOM_VALUE_TOO_LARGE` for one atom;
- `TREE_VALUE_BYTES_EXCEEDED` for aggregate atom content.

Structural mutation paths validate before commit. A rejected single-node edit,
transactional batch, task-scoped batch, merge candidate, or revert candidate must
leave its branch head and audit rows unchanged.

## Rendering

`render_node` bounds complete canonical and annotated responses with
`RENDERED_SOURCE_TOO_LARGE`.

Compiler materialization uses the separate source-map writer. That writer checks
the cumulative UTF-8 byte position before appending each fragment, including the
final newline. It therefore refuses an oversized canonical compiler source before
assembling the complete output string.

The source-map byte offsets, source hash, and retained compiler input remain
unchanged for accepted documents. Float atoms use the same canonical spelling in
plain rendering and compiler source maps, including integer-valued floats.

## Retained metadata

Stored `manifest.json` files used by build cache admission, `build_get`, and
`build_list_page` are limited to `MAX_BUILD_MANIFEST_BYTES`, currently 4 MiB.
Retained test-run and test-batch manifests are independently limited to
`MAX_TEST_RUN_MANIFEST_BYTES` and `MAX_TEST_BATCH_MANIFEST_BYTES`, also 4 MiB.
Tested-merge attestations use `MAX_TESTED_MERGE_ATTESTATION_BYTES`, likewise 4
MiB.

These files are opened through a race-resistant retained-artifact reader that
rejects symlinks, non-regular files, path replacement during open, invalid UTF-8,
invalid JSON, and limit overflow before normal identity, checksum, aggregate, and
referenced-evidence verification runs.

The accepted manifest schemas and public integrity-error contracts remain
unchanged. These protections bound metadata decoding; they do not impose total
build-root, run-root, batch-root, or attestation-root storage quotas.

## Stable limits and compatibility

Limit changes can alter whether an existing but unusually large document remains
editable or buildable. They are operational compatibility changes and require:

- explicit review;
- regression tests at and above the boundary;
- real MCP qualification;
- documentation updates;
- migration or export guidance when lowering a limit below previously accepted
  data.

Stored historical snapshots are not rewritten by this change. Reading a
historical document through a path that validates or renders it may reject that
document if it exceeds the current safety contract. A future database integrity
command should report such oversized historical content explicitly.

## Remaining process boundaries

These structural and retained-manifest ceilings do not by themselves bound:

- compiler stdout and stderr;
- retained WIR size;
- SQLite database size;
- aggregate retained build and test artifact storage;
- virtual-candidate qualification manifest size.

Compiler process capture and protocol-file bounds are a separate boundary because
they require explicit truncation/error evidence in build and validation result
formats. The remaining virtual-candidate manifest family, artifact quotas, and
database quotas require explicit operator policies rather than being inferred
from structural source limits.
