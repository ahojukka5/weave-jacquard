# Jacquard

**Jacquard is the agent-native programming environment for Weave.** Coding
agents edit a versioned S-expression tree through structural MCP operations
instead of repeatedly replacing complete source files.

The name refers to the Jacquard loom: a programmable mechanism that turns a
stored pattern into coordinated weaving operations. Here, agents modify the
program pattern, Jacquard preserves its structure and history, and `weavec`
turns the canonical result into a native executable.

Repository and Python distribution: **`weave-jacquard`**  
Public Python namespace: **`weave_jacquard`**  
Primary executables: **`weave-mcp`** and **`weave-build`**

## Responsibilities

Jacquard owns:

- single-node and bounded transactional edits with stable node identities;
- immutable revisions, parallel branches, deterministic one-call merge preflight,
  revisioned target-authoritative merge policy, directional target impact,
  complete affected-target compiler gates, race-safe publication, measured branch
  activity, and bounded stable-node revision diffs;
- project-, document-, and symbol-scoped context;
- compiler-corpus-backed grammar help;
- authoritative validation through `weavec --frontend`;
- revisioned named build targets and ordered multi-document builds;
- deterministic canonical sources and per-document node maps;
- compiler diagnostics mapped back to database nodes and exposed in bounded pages;
- verified, content-derived native build artifacts.

Jacquard is not another compiler. The user-facing
[`weavec`](https://github.com/ahojukka5/weavec) compiler owns the Weave language,
surface lowering, WIR, LLVM generation, runtime selection, object generation,
and linking.

## Architecture

The supported workspace is `SExpressionWorkspace`. It inherits a small internal
grammar-neutral revision service responsible only for:

- SQLite lifecycle;
- projects, branches, checkout, and history;
- immutable state load and commit;
- common-ancestor discovery;
- merge preview and publication through workspace-specific stable-ID hooks.

Language structure is not duplicated in Python; `weavec` remains authoritative.
The current implementation package remains internal, while new public imports
use `weave_jacquard`.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Configure the workspace and compiler:

```bash
export WEAVE_DB_PATH="$PWD/weave.db"
export WEAVE_BUILD_ROOT="$PWD/.weave-build"
export WEAVEC_BIN="../weavec/build/weavec"
export WEAVEC_SOURCE_ROOT="../weavec"
```

`WEAVEC_BIN` is optional when `weavec` is on `PATH`.
`WEAVEC_SOURCE_ROOT` is required only for compiler-corpus-backed grammar help.

Native builds require `weavec >= 0.3.0`, or another compiler implementing:

- `weavec build`;
- `weavec-build-manifest-v1`;
- `weavec-diagnostics-v1`.

Run the stdio MCP server:

```bash
weave-mcp
```

## Recommended agent workflows

A protected project may first publish a strict target-branch policy:

```text
merge_policy_set(
  require_preflight = true,
  require_affected_validation = true,
  allow_uncovered_documents = false,
  max_affected_targets = project-appropriate bound)
```

Single-document program:

```text
project_initialize
→ program_create / program_import
→ grammar_help
→ single-node edits while exploring
→ node_apply_batch for a coherent known structure
→ node_inspect
→ program_validate
→ branch_merge_preflight
→ review policy, ready_for_publication, impact, coverage, and validation_set
→ branch_merge using returned publication_arguments
→ branch_activity_summary when measuring the workflow
→ program_build
→ build_get
→ build_diagnostics_page when the build failed
→ node_inspect(revision_id = failed revision) before repair
→ revision_diff_page(base_revision_id = failed revision) against current head
```

Multi-document program:

```text
program_source_list
→ build_target_set
→ structural source edits
→ build_target_validate
→ branch_merge_preflight
→ review target policy, every affected surviving target, and uncovered document
→ branch_merge using returned publication_arguments
→ build_target_build
→ build_get
→ build_diagnostics_page when the build failed
→ node_inspect(revision_id = failed revision) before repair
→ revision_diff_page(base_revision_id = failed revision) against current head
```

A target definition and every selected source are resolved from one immutable
revision or from one exact in-memory merge candidate. The primary document is
first and additional documents retain their stored order.

`node_apply_batch` accepts a flat list of up to 256 existing structural
operations. Temporary `@aliases` refer to nodes created earlier in the same
request. The complete batch publishes as one revision or rolls back; existing
single-node tools remain available for uncertain edits and repairs.

For independent branches, `branch_merge_preflight` composes the complete
non-mutating review sequence:

```text
target-branch merge policy
+ visible source-branch policy
+ stable-ID merge preview
+ directional named-target impact
+ candidate target coverage
+ every affected surviving target validated by weavec --frontend
```

The response identifies the exact common ancestor and branch heads, prospective
merged-root hash, bounded affected-target summary, uncovered changed documents,
complete validation set, and `ready_for_publication`. A ready result includes
`publication_tool="branch_merge"` and exact `publication_arguments`, including
its policy-bound `preflight_id`.

The preflight result is evidence rather than a bearer token. Calling the returned
publication operation recomputes the current policies, impact, coverage, and all
affected-target frontend validations. Both branch heads are then rechecked in the
same SQLite write transaction that publishes the immutable two-parent merge.

## Revisioned merge policy

`merge_policy_set` publishes an immutable policy revision directly on a selected
branch. `merge_policy_get` reproduces the effective first-parent policy at a
branch head or exact historical project revision.

A policy may require:

- exact preflight replay;
- complete affected-target validation;
- rejection of uncovered-document overrides;
- a lower synchronous affected-target validation ceiling.

The current **target branch** policy governs admission. The source branch policy
is returned for transparency, and `source_policy_ignored=true` reports a
difference, but the incoming branch cannot weaken its own admission rules. To
loosen a protected branch, publish `merge_policy_set` directly on that target
branch. That policy revision changes the branch head and invalidates older
preview and preflight evidence.

When no policy is configured, Jacquard preserves the existing API and merge
modes. A configured strict policy may return:

- `MERGE_POLICY_PREFLIGHT_REQUIRED`;
- `MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED`;
- `MERGE_POLICY_VIOLATION`;
- `STALE_MERGE_PREFLIGHT`;
- `TOO_MANY_AFFECTED_TARGETS`.

Uncovered changed documents block strict preflight before compiler startup.
Permitting them requires both a target policy that allows the override and an
explicit `allow_uncovered_documents=true` request; it still does not claim those
documents were validated.

The lower-level tools remain useful for focused investigation:

- `branch_merge_preview` reports structural conflicts and stable-node
  consequences;
- `branch_merge_impact` pages directional named-target consequences;
- `branch_merge_validate` validates one named target;
- `branch_merge_validate_affected` returns the complete bounded validation set.

Compiler rejection returns `MERGE_VALIDATION_FAILED`; missing compiler
availability returns `MERGE_VALIDATION_UNAVAILABLE`; uncovered documents return
`MERGE_UNCOVERED_DOCUMENTS`; branch advancement returns `STALE_MERGE_PREVIEW`.
Every failure leaves the target branch unchanged. Direct merge compatibility is
preserved only where the effective target policy permits it.

For long branches, `branch_history_page` returns bounded first-parent pages with
an explicit continuation. `revision_operations_page` returns exact immutable
operation targets and payloads for one revision in sequence-number pages.
`branch_activity_summary` reports complete revision, operation, merge, author,
and edit-grouping metrics without changing history.

For failed builds, `build_diagnostics_page` returns exact mapped diagnostics in
bounded pages after verifying the immutable build and the bytes being read. An
agent can follow a returned stable `node_id` without opening files on the MCP
server machine. Passing the returned build `revision_id` to `node_inspect`
reproduces the exact failing subtree even after the branch has advanced. Without
`revision_id`, the same tool continues to inspect the current branch head.

`revision_diff_page` then compares the failing revision with the current branch
head without loading two complete trees. It reports additions, removals, value
changes, form-head changes, parent and position changes, and child-count changes
through stable IDs in pages of at most 200 changed nodes.

## Compiler boundary

Validation invokes only the public compiler frontend:

```text
weavec --frontend output.wir source0.weave source1.weave ...
```

Native builds invoke only the public build command:

```text
weavec build source0.weave source1.weave ... -o program \
  --manifest-json compiler-manifest.json \
  --diagnostics-json compiler-diagnostics.json
```

Jacquard never invokes LLVM tools, a linker, or a runtime archive directly.

## Stable node identities

Every list and atom has a stable ID such as `n_3a12cce48fe14f99`. Editing or
moving an existing node preserves its ID. Branches inherit IDs from their base
revision, merge compares stable identities rather than line numbers, and
`revision_diff_page` uses those identities to compare immutable states.

Agent rendering may expose transport wrappers:

```lisp
(@n_function
  (fn main
    (@n_params (params))
    (@n_returns (returns i32))
    (@n_body (do (return (const_i32 42))))))
```

Those wrappers are not Weave syntax. Compiler sources are canonical unannotated
text. A separate `weave-node-map-v1` records node IDs and UTF-8 source spans.

## Builds and integrity

A successful build contains:

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

The bridge validates both compiler protocol documents before retaining an
executable. `build_get` and cache admission verify the frontend manifest, build
ID, path containment, regular-file status, and every SHA-256 hash.
`build_diagnostics_page` performs the same verified admission and hashes the
exact diagnostic bytes it decodes before returning mapped entries.

`weave-build-key-v4` derives the build ID from the immutable revision, ordered
source hashes, compiler binary hash, and requested target. Concurrent builds use
a per-build advisory lock. An existing verified successful build wins; failed
or incomplete candidates cannot erase it.

The historical protocol identifier `weave-frontend-build-manifest-v2` remains
unchanged for stored-build compatibility. It names a data format, not the
current product.

## Revision storage

Each successful single-node write creates one immutable revision. A bounded
transaction records every ordered sub-operation while publishing one immutable
revision for the complete batch. Merge policies are immutable context documents
referenced by operation rows and require no database schema extension. Snapshot
JSON uses an adaptive, versioned BLOB representation:

- `WJZ1` for zlib-compressed canonical JSON;
- `WJR1` when raw canonical JSON is smaller.

Legacy databases migrate transactionally. Databases with a newer schema version
are rejected without modification.

## CLI

```bash
weave-build --db weave.db target-set demo application main.weave \
  --source library.weave
weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application
weave-build --db weave.db get <build-id>
```

Failures are emitted as structured JSON on stderr with exit status 2.

## MCP tools

- **Help:** `weave_help`, `grammar_help`
- **Projects and branches:** `project_initialize`, `branch_create`,
  `branch_list`, `branch_history`, `branch_history_page`,
  `revision_operations_page`, `branch_activity_summary`, `merge_policy_get`,
  `merge_policy_set`, `branch_merge_preflight`, `branch_merge_preview`,
  `branch_merge_impact`, `branch_merge_validate`,
  `branch_merge_validate_affected`, `branch_merge`
- **Programs:** `program_create`, `program_import`, `program_list`,
  `program_source_list`, `program_render`, `program_validate`, `program_build`
- **Named targets:** `build_target_set`, `build_target_list`,
  `build_target_get`, `build_target_delete`, `build_target_validate`,
  `build_target_build`
- **Build inspection:** `build_get`, `build_diagnostics_page`
- **Single-node editing:** `node_create_form`, `node_add_atom`, `node_set_atom`,
  `node_move`, `node_wrap`, `node_delete`
- **Transactional editing:** `node_apply_batch`
- **Inspection:** `node_inspect`, `node_find`, `revision_diff_page`
- **Context:** `context_add`, `context_get`

## Further documentation

- [Architecture](docs/architecture.md)
- [MCP tool reference](docs/mcp.md)
- [Transactional structural edits](docs/edit-transactions.md)
- [Branch activity observability](docs/branch-activity.md)
- [Revisioned merge admission policy](docs/merge-policy.md)
- [One-call merge preflight](docs/merge-preflight.md)
- [Two-phase merge previews](docs/merge-preview.md)
- [Merge target impact analysis](docs/merge-impact.md)
- [Affected-target validation sets](docs/merge-validation-set.md)
- [Merge candidate validation](docs/merge-validation.md)
- [Build diagnostic inspection](docs/build-diagnostics.md)
- [Revision-pinned node inspection](docs/revision-node-inspection.md)
- [Stable-node revision diffs](docs/revision-diff.md)
- [Compiler bridge](docs/compiler-bridge.md)
- [Revisioned build targets](docs/build-targets.md)
- [Target validation](docs/target-validation.md)
- [Snapshot storage](docs/snapshot-storage.md)
