# Optimistic concurrency for program and build-target writes

## Purpose

Program documents and named build targets are revisioned branch state. Their
write tools must not load an old branch snapshot and later overwrite a newer
revision published by another agent.

The following MCP tools use transactional branch-head compare-and-set semantics:

- `program_create`;
- `program_import`;
- `build_target_set`;
- `build_target_delete`.

## Request and response contract

Each tool preserves its existing arguments and adds:

```text
expected_revision_id = optional non-empty branch-head revision
```

Every successful result adds:

```text
base_revision_id = exact immutable revision read and mutated
```

Prepared agents should pass the revision from the read or write result on which
the next operation was planned. Existing callers may omit the request field and
ignore the response extension.

## Publication sequence

Each write:

1. validates `expected_revision_id` when supplied;
2. captures the current branch head;
3. rejects a mismatching prepared base with `STALE_BRANCH_HEAD`;
4. loads all program and reserved metadata documents from that exact revision;
5. applies the normal parser, tree builder, document, target, and structural
   validation rules;
6. writes the new immutable revision, snapshots, and operation audit row;
7. advances the branch only when it still points to `base_revision_id`.

Steps 6 and 7 occur in one SQLite transaction. A mid-call concurrent branch
advance rolls back all newly inserted revision state.

## Program writes

`program_create` retains the historical program, name, and version tree shape and
its `create_program` operation kind.

`program_import` retains canonical S-expression parsing, `replace` behavior, and
its `import_program` operation kind. The parser may run before branch capture,
but no branch state is selected or mutated until the exact write base is
captured.

A stale prepared create/import publishes no document snapshot or operation row.
An unprepared write is still race-safe and reveals its selected base afterward.

## Build-target writes

`build_target_set` reuses the existing name, document-set, compiler-target,
program-document, and structural validation. Updating an existing target keeps
its root stable ID through the historical tree builder.

`build_target_delete` verifies the target exists in the captured state before
removing its reserved storage document.

Both tools preserve:

- `@build-target/<name>` storage document names;
- `set_build_target` and `delete_build_target` audit operation kinds;
- ordered source-document semantics;
- native target normalization;
- target read, validation, and build behavior.

## Errors

- `INVALID_EXPECTED_REVISION_ID`: expectation is empty or not a string;
- `STALE_BRANCH_HEAD`: prepared base is no longer current, or the branch advances
  before publication;
- existing program and target validation/not-found errors remain unchanged.

Failures leave the branch head, revision count, operation count, and retained
program/target state unchanged.

## MCP composition

The production entry point installs the full race-safe public
`SExpressionWorkspace` before any service populates the workspace cache. It then
replaces the historical program and node registrations under their existing
names.

A final build-target extension replaces only `build_target_set` and
`build_target_delete`, and makes the shared target-registry cache instantiate the
race-safe registry. Target reads, validation, builds, merge impact, and merge
validation use that same registry and workspace.

## Compatibility

No database schema, revision representation, program snapshot, target metadata,
compiler protocol, build key, or source-language behavior changes. Public tool
names and existing positional arguments remain compatible.

## Qualification

Direct tests prove:

- exact base provenance for create, import, replace, target set/update/delete;
- unchanged program and target operation kinds;
- target root-ID preservation on update;
- stale prepared rejection without new revision or operation rows;
- a forced unprepared program race using two SQLite connections.

The real stdio MCP test proves all four public schemas expose
`expected_revision_id`, exercises prepared and unprepared writes, rejects stale
program and target requests, confirms the branch remains unchanged after
rejection, and retains `program-target-concurrency-trace.json` in standard CI.

The packaged compiler workflow remains the regression gate for target reads,
validation, native builds, merge impact, merge validation, policies, preflight,
and artifact discovery with the final shared workspace and registry installed.

## Remaining audit boundary

`context_add` and `merge_policy_set` require more than branch compare-and-set:
their content-addressed `documents` row and referencing revision must be
published in one transaction so a lost race cannot leave an orphan row. See
`write-concurrency-audit.md`.
