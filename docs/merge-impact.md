# Merge target impact analysis

## Purpose

A clean prospective merge may affect several named programs even when an agent
edited only one document. A primary source can be shared by many targets, an
additional source can feed a larger application, and target metadata itself can
be added, removed, or changed.

`branch_merge_impact` maps the exact current merge candidate to its revisioned
named build targets before compiler validation or publication:

```text
branch_merge_preview
→ branch_merge_impact
→ branch_merge_validate
→ branch_merge
```

The analysis is read-only. It creates no revision, compiler process, build
artifact, or branch update.

## Request

```text
branch_merge_impact(
  project,
  target_branch,
  source_branch,
  preview_id = optional reviewed preview,
  start_index = 0,
  limit = 50,
)
```

A supplied preview ID must still describe the current branch heads. Otherwise the
call returns `STALE_MERGE_PREVIEW`. A semantic merge conflict returns
`MERGE_CONFLICT` before target analysis.

Page limits are 1–200. When `has_more` is true, pass `next_index` as the next
`start_index`. The preview binds immutable revisions, so page order remains
stable until either branch advances.

## Target graph

Named target definitions are stored as revisioned `@build-target/<name>`
documents. For each target, Jacquard reads:

- primary document;
- ordered additional documents;
- compiler target.

The service compares the target branch state with the prospective merged state.
Targets are sorted by name and classified as:

- `added`: the target exists only in the candidate;
- `removed`: the target exists only at the current target head;
- `modified`: its document set or compiler target changed;
- `unchanged`: its definition is identical, but one of its source documents
  changed.

## Affected reasons

Each affected target includes one or more deterministic reasons:

- `target_added`;
- `target_removed`;
- `target_definition_changed`;
- `source_document_changed`.

`changed_source_documents` is the sorted intersection between changed program
documents and the union of the target's before/after source sets. This preserves
useful evidence when a target definition moves from one source set to another.

The `before` and `after` fields contain compact target configurations or `null`.
Complete source trees are never returned.

## Candidate coverage

The response separates:

- `changed_program_documents`;
- `changed_target_documents`;
- `candidate_covered_changed_documents`;
- `uncovered_changed_documents`.

Coverage is intentionally calculated from targets that exist **after** the
prospective merge. A removed target does not count as candidate coverage. This
prevents target deletion from hiding a changed source that no surviving program
will validate.

An uncovered document is not automatically invalid. It may be a draft, fixture,
or intentionally unbuilt source. It is an explicit review signal: automatic
affected-target validation cannot prove anything about that document through a
named target.

## Counts

The response reports:

- total target definitions before and after the merge;
- total affected target entries, including removed targets;
- unaffected target count among targets that survive in the candidate;
- bounded pagination fields.

A removed target is affected but is not subtracted from candidate unaffected
count because it no longer exists in the candidate target set.

## Determinism

For fixed project, merge direction, and two branch heads:

- preview ID is stable;
- changed document sets are sorted;
- target entries are sorted by target name;
- reasons use fixed classification order;
- pages contain no duplicates or omissions.

The complete internal analysis can therefore feed automatic validation without
reinterpreting user-visible pages.

## Recommended use

1. preview the merge;
2. inspect target impact;
3. review uncovered changed documents;
4. validate every surviving affected target;
5. publish only after all required validation gates pass.

The current tool provides steps 1–3 and the exact target input set for step 4.
Automatic all-affected-target validation is the next orchestration layer built on
this contract.
