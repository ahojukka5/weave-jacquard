# Selected merge-train previews

## Purpose

Independent merge previews compare every source branch with the same current
target head. They cannot answer a different question: what happens when several
sources are merged in a specific order and each clean result becomes the target
state for the next source?

`selected_merge_train_preview` simulates that ordered sequence in memory. It can
expose conflicts introduced by prior hypothetical merges, conflicts removed by a
bridge source, and later sources that become structurally redundant.

The train preview performs no compiler work, preflight, publication, or
persistent write.

## Request

```text
selected_merge_train_preview(
  project,
  target_branch,
  sources,
  catalog_id,
  conflict_limit = 20,
  changed_document_limit = 50)
```

Required inputs are:

- one project and explicit target branch;
- one exact project merge `catalog_id`;
- an ordered list of 1–10 unique source branch names.

The caller chooses the source set and order. Jacquard does not discover, rank,
expand, or reorder it.

## Response format and identity

The response format is:

```text
weave-selected-merge-train-preview-v1
```

`train_id` hashes the complete returned evidence, including:

- exact target and source catalog identity;
- selected source order;
- every virtual target root transition;
- original preview identities;
- train conflicts, changed documents, and redundancy;
- bounds, stopping state, and publication guidance.

Repeating the same ordered simulation against unchanged immutable evidence
produces the same train identity.

## Exact complete catalog

The train recomputes the same target/source catalog used by project merge queues:

- exact target branch and head revision;
- every source branch name and exact head revision.

The supplied `catalog_id` must match before simulation. The complete catalog is
recomputed after simulation as well, including unselected branches.

Any branch addition, removal, or head advance returns:

```text
STALE_SELECTED_MERGE_TRAIN_CATALOG
```

No partial train is returned under a stale catalog identity.

## Virtual target semantics

The initial virtual target state is the exact committed target-head state.

For each selected source in caller order:

1. Jacquard obtains the source's normal preview against the original target head;
2. it identifies the common ancestor of the original target head and source head;
3. it merges the source state into the current virtual target state using the
   normal stable-ID three-way merge algorithm;
4. it semantically validates the merged virtual state;
5. on success, the merged state becomes the virtual target for the next step.

The original committed target branch never moves. Virtual roots exist only in
the response and process memory.

Using the original target/source common ancestor for every source preserves the
source branch's actual history while allowing the virtual target to accumulate
changes from earlier train steps.

## Relation to the original preview

Every step compares train behavior with the source's normal preview against the
original target.

### `consistent_clean`

The original preview is clean and the ordered train step is also clean.

The train step can still produce fewer changes than the original preview because
prior sources may already have applied some or all of the same state.

### `consistent_conflict`

The original preview conflicts and the train step still conflicts when reached.

### `order_introduced_conflict`

The original source-to-target preview is clean, but prior virtual merges changed
the target so this train step conflicts.

This is direct structural evidence that independent previews are insufficient for
the selected order.

### `order_removed_conflict`

The original source-to-target preview conflicts, but prior virtual merges changed
the virtual target so the train step becomes clean.

This does not mean the source can be merged immediately into the committed target.
It means the selected prior train steps could structurally remove that conflict.
Actual publication must occur sequentially with fresh previews and preflight.

## Redundant later sources

A clean step reports:

```text
no_changes = true
```

when applying the source leaves the virtual target root unchanged.

This can occur when an earlier train source already produced the same relevant
state. It is structural redundancy evidence for the selected order only.

It does not prove the branch is obsolete, safe to delete, or unnecessary in
another target or order.

## Step evidence

Each simulated step reports:

- zero-based `step_index`;
- exact source branch and head revision;
- exact common-base revision;
- virtual target root before the step;
- virtual target root after a clean step;
- original `preview_id` and original mergeability;
- train-step mergeability;
- relation to the original preview;
- bounded conflicts and complete conflict count;
- bounded changed-document names and complete count;
- explicit conflict/document truncation;
- `no_changes`;
- whether real publication requires refresh after a prior step.

The first clean step is the only step whose original preview applies directly to
the current committed target head.

## First-conflict stopping

When a train step conflicts, there is no valid merged virtual target for the next
source. Simulation therefore stops immediately.

The top-level response reports:

- `train_complete`;
- `conflict_step_index`;
- simulated source count;
- successfully applied source count;
- `remaining_sources_not_simulated`;
- the last valid virtual target root.

Unsimmulated sources are not classified. Jacquard does not guess how they would
behave without a valid prior virtual state.

## Public bounds

Maximums are:

- 10 selected source branches;
- 100 returned conflict strings per conflicting step;
- 200 returned changed-document names per clean step.

Complete counts and explicit truncation preserve omitted evidence.

Invalid selections or bounds return:

- `INVALID_SELECTED_MERGE_TRAIN_SOURCES`;
- `INVALID_SELECTED_MERGE_TRAIN_SOURCE`;
- `INVALID_SELECTED_MERGE_TRAIN_CATALOG`;
- `INVALID_SELECTED_MERGE_TRAIN_TARGET`;
- `INVALID_SELECTED_MERGE_TRAIN_LIMIT`.

## No compiler or preflight

The train preview runs no:

- `weavec` frontend validation;
- named-target builds;
- merge impact or affected-target validation;
- merge preflight;
- merge publication.

It is a cheap structural planning layer that should be used before selecting
compiler-backed work.

A structurally complete train does not prove that each source passes target
policy, target coverage, compiler validation, or publication-head checks.

## Publication boundary

When the first train step is clean, the response contains:

```text
first_publication_candidate.tool = branch_merge_preflight
first_publication_candidate.arguments = {
  project,
  target_branch,
  source_branch,
  preview_id
}
```

That call is valid only for the current committed target head represented by the
catalog.

After publishing any real step:

1. the target branch head changes;
2. the original catalog becomes stale;
3. every later original preview and preflight identity is invalid;
4. the caller must obtain a fresh catalog;
5. the caller must preview and preflight the next source against the new target.

The train never returns publication arguments for later virtual steps because
those virtual target roots are not committed revisions.

## Caller order is structural input, not priority

Source order can change:

- whether a later source conflicts;
- whether an original conflict disappears;
- whether a later source becomes redundant;
- the final virtual target root.

This makes order an important algorithmic input. It still does not itself express
business priority, urgency, quality, age, ownership, or readiness.

## Read-only behavior

The train creates no:

- branch or revision;
- operation row;
- document or revision-document link;
- build, WIR, or compiler artifact;
- filesystem output;
- preflight or merge publication.

Only committed immutable state is read. Prospective merged states remain in
memory.

## Errors

Request-level failures include:

- normal project and branch not-found errors;
- structural branch-catalog fanout errors;
- invalid target, source, catalog, or public bounds;
- stale catalog before, during, or after simulation;
- semantic validation failures from a malformed prospective state.

Stable-ID merge conflicts are normal step evidence rather than request-level
errors. They stop the train and are returned in the successful response.

## Qualification

Direct tests prove:

- deterministic train identity;
- exact virtual root transitions;
- an order-introduced conflict between two sources independently clean against
  the original target;
- a later identical source becoming `no_changes`;
- an original conflict removed after a bridge source changes the virtual target;
- first-conflict stopping and unsimulated-source evidence;
- first-step preflight call and later refresh requirement;
- stale catalog rejection before simulation;
- complete catalog recheck after simulation, including an unselected branch;
- source and bound validation;
- shared production queue construction.

The production stdio lifecycle creates all three order effects, verifies every
branch head remains unchanged after train reads, advances an unselected branch,
and rejects the old catalog. Database inspection proves no merge revision or
train operation is written.

Standard CI retains `selected-merge-train-preview-trace.json`. The packaged
`weavec` workflow verifies that final MCP registration does not regress native
builds, merge publication, policies, preflight, checkpoints, project queues,
compiler-backed selected batches, or artifact discovery.

## Compatibility

The feature is additive and read-only. It reuses existing exact branch catalogs,
stable-ID three-way merge, immutable revision state, semantic validation, and
merge preview identity.

It changes no database schema, stored protocol, compiler interface, build key,
manifest, node ID, or Weave language rule.
