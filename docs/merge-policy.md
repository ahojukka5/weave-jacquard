# Revisioned merge admission policy

## Purpose

A safe merge workflow should not depend on every agent remembering the same
flags. Jacquard therefore supports a revisioned project policy that controls
admission into a selected target branch.

```text
merge_policy_set on protected branch
→ branch_merge_preflight
→ review target-authoritative policy and compiler evidence
→ branch_merge using returned publication_arguments
```

The policy controls workflow admission. It does not replace stable-ID merge,
compiler validation, or atomic branch-head checks.

## Policy format

Policies use:

```text
weave-merge-policy-v1
```

Fields:

- `require_preflight`: publication must replay an exact
  `branch_merge_preflight` identity;
- `require_affected_validation`: publication must validate every affected target
  that survives in the prospective merge;
- `allow_uncovered_documents`: whether callers may explicitly accept changed
  program documents with no surviving named-target coverage;
- `max_affected_targets`: the maximum affected surviving targets that one
  validation set may invoke, from 1 through the global bound of 64.

`require_preflight=true` requires `require_affected_validation=true` because the
preflight publication contract is the complete affected-target path.

## Setting a policy

```text
merge_policy_set(
  project,
  branch = "main",
  require_preflight = true,
  require_affected_validation = true,
  allow_uncovered_documents = false,
  max_affected_targets = 64,
)
```

Each successful call publishes a new immutable revision on that branch. Even an
identical policy creates a new audit revision, while its content document may be
deduplicated by hash.

The operation log records `set_merge_policy`, policy format, document identity,
and policy hash. Policy documents are project-scoped immutable context objects;
no database schema migration or compiler-source document is introduced.

## Reading policy history

```text
merge_policy_get(
  project,
  branch = "main",
  revision_id = optional exact project revision,
)
```

The registry walks the selected revision's first-parent history and returns the
latest policy-setting operation. Results include:

- effective policy fields;
- `configured`;
- selected revision and policy revision IDs;
- immutable document ID;
- deterministic policy hash.

Passing a historical revision reproduces the policy effective at that point.

## Compatibility when no policy exists

An unconfigured project preserves the existing merge API:

```text
require_preflight = false
require_affected_validation = false
allow_uncovered_documents = true
max_affected_targets = 64
configured = false
```

This compatibility policy is resolved but not stored. Existing direct,
single-target, and all-target merge calls remain valid until a project explicitly
publishes a policy.

## Target-branch authority

The target branch's current first-parent policy governs publication.

```text
protected target policy: strict
incoming source policy: permissive
result: strict target policy is enforced
```

A source branch policy is returned in preflight and merge results for review, but
it is not imported as target admission authority. `source_policy_ignored=true`
reports differing policy hashes.

This follows Jacquard's revision model:

- the merge revision's first parent is the current target head;
- revision context is inherited from that target first parent;
- source policy changes cannot smuggle a weaker rule into the target;
- changing target admission requires publishing `merge_policy_set` directly on
  the target branch.

The branch-head change caused by a policy update also invalidates earlier preview
and preflight identities.

## Policy-aware preflight

`branch_merge_preflight` resolves both branch policies before impact or compiler
work.

It:

1. selects the current target policy as authority;
2. returns the source policy for transparency;
3. rejects a forbidden uncovered-document override immediately;
4. applies the target's affected-target ceiling before compiler startup;
5. binds both policy hashes and the ignored-source signal into `preflight_id`;
6. returns `preflight_id` in `publication_arguments`.

A strict ready result therefore proves:

```text
exact branch heads
+ exact target policy
+ visible source policy
+ directional target graph
+ coverage policy
+ every selected frontend validation
```

## Publication enforcement

`branch_merge` retains its previous arguments and adds:

```text
preflight_id = optional deterministic preflight identity
```

A configured target policy may reject publication with:

- `MERGE_POLICY_PREFLIGHT_REQUIRED` when a required preflight ID is absent;
- `MERGE_POLICY_AFFECTED_VALIDATION_REQUIRED` when a weaker validation mode is
  selected;
- `MERGE_POLICY_VIOLATION` when an uncovered-document override is forbidden;
- `TOO_MANY_AFFECTED_TARGETS` when policy fanout is exceeded;
- `STALE_MERGE_PREFLIGHT` when recomputed evidence or policy differs.

When `preflight_id` is supplied, publication:

1. resolves the current target and source policies;
2. recomputes policy-aware preflight against current heads;
3. compares the exact preflight identity;
4. enforces complete validation-set readiness;
5. publishes using the validated preview ID;
6. rechecks both branch heads inside the SQLite write transaction.

The preflight is recomputed once and its validation set is used for publication;
Jacquard does not perform a redundant second compiler fanout before the same
transactional head check.

## Result evidence

Policy-aware merge results add:

- `merge_policy_enforced`;
- `target_merge_policy`;
- `source_merge_policy`;
- `source_policy_ignored`;
- `preflight_enforced`;
- `preflight_id`.

The effective target policy is also historically recoverable from the merge
revision's first parent, so reviewers do not need a mutable external policy
store to reproduce admission rules.

## Recommended strict policy

For protected integration branches:

```text
require_preflight = true
require_affected_validation = true
allow_uncovered_documents = false
max_affected_targets = a project-appropriate bounded value
```

A lower fanout limit is useful when compiler startup cost or synchronous MCP
latency requires a smaller review unit. Split large target-graph changes or
explicitly revise the target policy; do not silently bypass the limit.
