# Revisioned named build targets

## Purpose

Named build targets let agents refer to a stable build recipe instead of
repeating a long ordered document list and compiler target on every call.

```text
build target app
├── primary: main.weave
├── sources:
│   ├── library.weave
│   └── platform.weave
└── compiler target: native
```

A target is project metadata inside the same immutable revision graph as its
source documents. It is not a mutable preference table and is not stored in the
compiler.

## Storage model

Targets are structural S-expression metadata stored under the reserved document
namespace:

```text
@build-target/<name>
```

The stored form is:

```lisp
(build-target
  (primary "main.weave")
  (source "library.weave")
  (source "platform.weave")
  (compiler-target "native"))
```

`compiler-target` is always present. `native` means that the installed `weavec`
package chooses its own native target. An explicit target triple may be stored
instead.

This representation deliberately uses the existing immutable structural
snapshot and merge machinery:

- target creation or update creates a new revision;
- checkout restores the target definitions from that revision;
- ordinary source edits preserve targets automatically;
- branch merge combines independent target and source changes;
- incompatible edits to the same target field produce a normal structural
  merge conflict;
- the project root hash includes target definitions because they are part of
  revision state.

Stable node IDs are retained for the target root, field forms, field heads, and
existing values when a target is updated. This is required for meaningful
three-way merge behavior.

## Source safety

Reserved target metadata is never passed to `weavec`. Target creation validates
that every selected source:

- exists in the same project revision;
- has a non-empty document name;
- is not another `@build-target/...` record;
- appears at most once in the ordered source set.

`program_source_list` and `weave-build source-list` list compiler source
documents without reserved target metadata. The lower-level `program_list`
continues to describe every structural document in the revision, including
reserved metadata, for database inspection and debugging.

## MCP tools

### Create or update

```text
build_target_set(
  project="demo",
  name="app",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"],
  compiler_target="native",
  branch="main"
)
```

Omitting `compiler_target` stores `native` explicitly.

### Read and list

```text
build_target_get(project="demo", name="app", branch="main")
build_target_list(project="demo", branch="main")
```

Both operations may receive an exact `revision_id` instead of reading the
current branch head.

### Build

```text
build_target_build(project="demo", name="app", branch="main")
```

The operation resolves the branch once, reads the target and all selected source
documents from that exact revision, and calls the normal `CompilerBridge`.
The response includes the regular build manifest plus request-level target
provenance:

```json
{
  "build_target": {
    "name": "app",
    "revision_id": "...",
    "document": "main.weave",
    "additional_documents": ["library.weave", "platform.weave"],
    "compiler_target": "native"
  }
}
```

The target name is request provenance rather than binary identity. An ad-hoc
build and named-target build of the same revision, source order, compiler, and
native target intentionally reuse the same content-addressed artifact.

### Delete

```text
build_target_delete(project="demo", name="app", branch="main")
```

Deletion creates a new revision. Older revisions continue to expose the target.

## CLI

```bash
weave-build --db weave.db target-set demo app main.weave \
  --source library.weave \
  --source platform.weave

weave-build --db weave.db target-list demo
weave-build --db weave.db target-get demo app
weave-build --db weave.db target-build demo app
weave-build --db weave.db target-delete demo app
weave-build --db weave.db source-list demo
```

Use `--compiler-target <triple>` on `target-set` for a non-native target. Use
`--revision <id>` on read/list/build operations to pin an exact historical
target definition.

## Merge semantics

Target fields are ordinary stable-ID structural nodes. For example, starting
from:

```lisp
(build-target
  (primary "main.weave")
  (compiler-target "native"))
```

one branch may add `(source "library.weave")` while another changes
`compiler-target`. The merge combines both changes.

If both branches change the same `compiler-target` value differently, merge
reports a conflict. Because `compiler-target` always exists, two branches cannot
silently create duplicate target fields as independent additions.

## Current limitation

Reserved target records share the generic structural snapshot store with source
documents. This is intentional so revision hashing, checkout, and merge remain
one coherent transaction model. Higher-level source listing hides them, while
low-level database inspection still exposes them.
