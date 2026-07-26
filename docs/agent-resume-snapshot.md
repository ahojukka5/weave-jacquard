# Revision-pinned agent resume snapshots

## Purpose

A restarted or disconnected coding agent often knows the project and branch but
no longer holds the exact revision, document set, target definitions, policy,
context, or recent history in working memory. Recovering those pieces through
separate calls risks mixing an older inspected revision with a newer branch head.

`branch_resume_snapshot` provides one bounded orientation read from one immutable
project revision.

## Request

```text
branch_resume_snapshot(
  project,
  branch = "main",
  revision_id = optional,
  document_limit = 100,
  target_limit = 50,
  target_source_limit = 50,
  context_limit = 20,
  branch_limit = 50,
  history_limit = 10,
  operation_limit = 50)
```

Omitting `revision_id` selects the current branch head. Supplying it selects one
project-owned immutable revision, even when that revision is historical or no
longer reachable from the selected branch.

The selected branch must exist because the response reports its current head for
comparison.

## Revision consistency

The response reports:

- `branch_head_revision_id`, the selected branch's current head at call time;
- `revision_id`, the immutable state actually summarized;
- `revision_is_branch_head`, whether those IDs are equal.

When `revision_id` is explicit, every substantive project field comes from that
revision:

- revision root and parent identity;
- program documents and canonical source hashes;
- build-target definitions;
- effective first-parent merge policy;
- linked context documents;
- operation audit rows;
- first-parent history beginning at that revision.

The newer branch head is comparison metadata only. It must not influence the
selected programs, targets, policy, context, operations, or history.

The project branch list is intentionally current project-level orientation data.
Each entry includes its exact head revision, so it is never presented as part of
the selected immutable program state.

## Format and identity

The response format is:

```text
weave-agent-resume-snapshot-v1
```

`snapshot_id` is SHA-256 over the complete returned response before the ID field
is added. Repeating a call with the same immutable database evidence and the same
bounds produces the same ID. Changing the selected revision, a current branch
head, branch list, or output bounds may change the ID because the returned
orientation evidence changed.

The response includes the effective limit values used for the call. The snapshot
is read-only. It creates no branch, revision, operation, context, build, compiler
artifact, or filesystem output.

## Program summaries

Each returned program document contains:

- document name;
- stable root node ID;
- root form head;
- node count;
- SHA-256 of deterministic canonical compiler source;
- UTF-8 source byte count.

The source body and full node map are omitted. Use `program_render`,
`node_inspect`, or `node_find` with the returned `revision_id` for detailed
historical reads.

Reserved build-target metadata documents are excluded from the program list and
reported through `build_targets` instead.

## Build targets and policy

Build targets are parsed through the normal revisioned target registry. Each
summary contains:

- name and stable target-root ID;
- primary source;
- total and returned additional-source counts;
- bounded ordered additional sources and an explicit truncation flag;
- requested compiler target.

`target_limit` bounds target definitions. `target_source_limit` independently
bounds the additional source list inside each returned target. The primary source
is always reported.

Every returned target is checked against program documents in the exact selected
revision. A target cannot borrow a source from the current branch head.

`merge_policy` is resolved through the same first-parent policy registry used by
merge preflight and publication. An unconfigured historical state returns the
normal explicit default-policy result rather than borrowing a later policy.

## Context previews

Linked context rows are sorted deterministically and contain:

- document ID;
- scope kind and name;
- title;
- content hash;
- body byte count;
- up to 512 characters of body preview;
- an explicit truncation flag.

Policy documents are context documents and therefore may appear in the context
summary in addition to the parsed effective `merge_policy`.

## Operations and history

`operations` contains the bounded ordered audit rows attached directly to the
selected revision, including parsed JSON payloads.

`history` follows `parent1_id` beginning at the selected revision. It reports:

- returned count;
- `has_more`;
- `next_revision_id` for continuation through dedicated history tools;
- compact immutable revision rows.

Second merge parents are reported on each revision but are not traversed by the
first-parent resume history.

## Bounded work

All public limits are positive integers. Maximums are:

- 200 program documents;
- 100 build targets;
- 200 additional sources per returned target;
- 100 context documents;
- 200 project branches;
- 50 first-parent history entries;
- 200 current-revision operations.

Program, target, branch, context, and operation collections use count-plus-limit
queries. A small return limit does not require full target parsing or full branch
enumeration. Program source rendering is performed only for returned documents.

Each bounded collection reports total count, returned count, and a truncation
flag. Each target reports the same evidence for its nested additional-source
list. History reports its own continuation. Invalid limits return
`INVALID_RESUME_SNAPSHOT_LIMIT` before project state is summarized.

## Reproducible follow-up actions

The snapshot includes a partially filled exact-fork call:

```text
reproducible_fork.tool = branch_create_at_revision
reproducible_fork.arguments = {project, revision_id}
```

The agent supplies a new branch name.

It also includes a verified build-recovery call filtered to the exact revision:

```text
build_recovery.tool = build_list_page
build_recovery.arguments = {project, revision_id}
```

The response explicitly states that build discovery is lexical by content-derived
build ID, not chronological. The snapshot never invents a “latest build.”

## Errors

- missing branch or project uses the normal not-found contract;
- a foreign or unknown explicit revision is rejected as not belonging to the
  selected project;
- invalid bounds return `INVALID_RESUME_SNAPSHOT_LIMIT`;
- malformed historical target metadata or missing target sources use the normal
  target/document validation contract.

No partial snapshot is returned on request-level failure.

## Qualification

Direct tests prove:

- deterministic repeated IDs;
- exact revision/root identity;
- canonical source hashes and byte counts;
- named targets, policy, context previews, operations, branches, and history;
- historical isolation after later source and policy changes;
- top-level and nested target-source truncation evidence;
- validation of every bound;
- foreign-revision rejection.

The production stdio lifecycle creates a reviewed three-document state with a
multi-source build target, context, merge policy, and historical branch. It then
advances main and proves reviewed, historical, current, and deliberately
truncated snapshots remain internally consistent.

Standard CI retains `resume-snapshot-trace.json`. The packaged `weavec` workflow
verifies that the final MCP registration does not regress native builds, merge
admission, policies, preflight, or artifact discovery.
