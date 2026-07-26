# Revision-pinned rendering and node search

## Purpose

Jacquard already supports exact immutable revisions for build targets, source
listing, builds, diagnostics, stable-node inspection, and revision diffs.
`program_render` and `node_find` complete that historical read model.

Both tools preserve their original branch-head behavior when `revision_id` is
omitted. Supplying `revision_id` reads the exact project-owned immutable state
without checking out, rewriting, or advancing any branch.

## Revision selection

Both requests use:

```text
project
branch
document
revision_id = optional exact immutable revision
```

The selected branch must exist. The response reports:

- `branch_head_revision_id`: the current selected branch head;
- `revision_id`: the immutable state actually read;
- `revision_is_branch_head`: whether those identities are equal.

An explicit revision must belong to `project`. It does not need to remain the
branch head, be first-parent reachable from the branch, or be related to the
branch by ancestry. A revision from another project is rejected.

A document missing from the selected revision is reported as missing even when a
newer branch head contains a document with the same name.

## `program_render`

```text
program_render(
  project,
  branch,
  document,
  annotated = true,
  annotate_atoms = false,
  revision_id = optional)
```

The existing result object remains compatible and now additionally includes:

- project and branch;
- branch-head and selected-revision identities;
- `revision_is_branch_head`;
- `annotate_atoms`;
- `root_node_id`.

`source`, `document`, and `annotated` retain their prior meanings. Canonical and
annotated rendering always use the exact selected tree. Rendering is read-only.

## `node_find`

```text
node_find(
  project,
  branch,
  document,
  head = optional,
  kind = optional,
  value = optional,
  limit = 50,
  revision_id = optional)
```

For compatibility, the MCP response keeps `result` as the same list of node
matches returned by earlier versions. Each match retains:

- `node_id`;
- kind, form head, or atom value;
- parent stable ID;
- sibling position.

Revision metadata is added beside `result` in the MCP response envelope:

```json
{
  "ok": true,
  "result": [],
  "project": "demo",
  "branch": "main",
  "document": "main.weave",
  "branch_head_revision_id": "...",
  "revision_id": "...",
  "revision_is_branch_head": false,
  "matched_count": 0
}
```

This preserves exact revision identity even when no node matches. Existing
callers that read only `ok` and `result` remain compatible.

## Repair and review workflow

A deterministic historical investigation can now use one revision consistently:

```text
build_diagnostics_page
→ node_inspect(revision_id = failed build revision)
→ node_find(revision_id = failed build revision)
→ program_render(revision_id = failed build revision)
→ revision_diff_page(base_revision_id = failed build revision)
```

The same stable node IDs can then be inspected in the current branch head before
a structural repair. No read tool silently switches the requested historical
state to the current source view.

## Qualification

The real stdio MCP qualification:

1. creates a program and an atom with value `1`;
2. records that immutable revision;
3. changes the same stable atom to `2` on the branch head;
4. proves default rendering and search expose `2` at the head;
5. proves exact historical rendering and search expose `1` with the same node ID;
6. proves a zero-match head search still reports exact revision metadata;
7. retains `revision-reads-trace.json` as CI qualification evidence.

The test requires no compiler because this is a database/rendering boundary, not
a language-validation or native-build boundary.
