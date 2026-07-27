# Immutable reverts

Jacquard reverts one selected first-parent revision by applying its inverse to the
current branch head. The operation creates a new revision; it never resets a branch,
deletes revisions, or rewrites existing history.

## Workflow

```text
branch_history_page
→ select one first-parent revision
→ branch_revert_preview
→ inspect conflicts, changed_documents, and document_changes
→ run any compiler or behavioral checks required by the project
→ branch_revert with the exact preview_id
```

`branch_revert` always requires `preview_id`. The preview identity binds:

- project and branch;
- current branch head;
- selected revision;
- selected revision's first parent.

If the branch advances, publication fails with `STALE_REVERT_PREVIEW` and leaves the
branch unchanged.

## Stable-ID inverse semantics

The prospective state is produced with the existing stable-ID three-way merge engine:

```text
base   = selected revision
ours   = current branch head
theirs = selected revision's first parent
```

This makes the selected first-parent delta run in reverse while preserving independent
later edits. A later edit to the same stable node or document region is not guessed
through; it becomes an explicit conflict.

The selected revision must be reachable from the current branch head through the
first-parent chain. The initial project revision cannot be reverted because it has no
first parent. A merge revision can be selected; its inverse is defined relative to its
first parent.

## Preview result

`branch_revert_preview` is non-mutating and returns:

- the exact selected revision and first parent;
- the current branch head;
- `revertible` and bounded structural conflicts;
- `would_change_branch`;
- changed documents and per-document stable-node summaries;
- current, selected, parent, and prospective root hashes;
- deterministic `preview_id`.

A conflict-free preview that would reproduce the current state is a no-op. Publication
rejects it with `REVERT_NO_CHANGES` rather than creating meaningless history.

## Integrity checks

Before a preview is considered publishable, Jacquard validates the complete prospective
state:

- every structural tree is valid;
- every build target references existing non-metadata program documents;
- every test target references an existing build target;
- every task contract references existing allowed documents, dependencies, and required
  tests;
- task dependency cycles remain forbidden.

The same build-target source integrity check is shared by normal merge preview, so merge
and revert cannot publish a build target whose source document disappeared.

## Publication and audit evidence

A successful publication creates one new single-parent revision. Its parent is the exact
branch head reviewed by the preview. The immutable operation row records:

- preview ID;
- reverted revision and first parent;
- reviewed branch head;
- prospective root hash;
- changed documents.

The result explicitly reports `history_rewritten=false`.

## Boundary

Revert preview validates structural and project-metadata integrity only. It does not run:

- `weavec --frontend` validation;
- native builds;
- behavioral tests;
- merge-policy admission;
- human approval or production-readiness checks.

Call the relevant validation and test tools after preview and before publication when the
project requires them.

## Local qualification

Install development dependencies and run the retained qualification script:

```bash
python -m pip install -e '.[dev]'
bash scripts/qualify-immutable-revert.sh focused
bash scripts/qualify-immutable-revert.sh full
```

The script writes a reproducible bundle under
`local-qualification/immutable-revert/`, including environment metadata, syntax and Ruff
logs, pytest output, the real stdio MCP lifecycle trace, and SHA-256 checksums.
