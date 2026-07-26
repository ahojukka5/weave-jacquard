# Merge candidate validation

## Purpose

A structurally clean three-way merge can still be an invalid Weave program.
Independent branches may each validate while their combined definitions introduce
a duplicate symbol, missing call target, incompatible signature, or another
cross-branch semantic failure.

Jacquard therefore supports authoritative validation **before** the target branch
moves:

```text
branch_merge_preview
→ branch_merge_validate
→ branch_merge(preview_id, validation_target)
```

`branch_merge_validate` invokes the configured final `weavec --frontend` on the
exact in-memory merge candidate. It does not create a revision, advance a branch,
publish a build, or retain compiler artifacts.

## Request

```text
branch_merge_validate(
  project,
  target_branch,
  source_branch,
  build_target,
  preview_id = optional reviewed preview
)
```

The named build target is resolved from the prospective merged state, not from
only the target or source branch. Its primary document and additional documents
retain their stored order.

When `preview_id` is supplied, either branch advancing before validation returns
`STALE_MERGE_PREVIEW`. A semantic merge conflict returns `MERGE_CONFLICT` before
the compiler is started.

## Exact candidate

The service recomputes the same stable-ID three-way merge used by
`branch_merge_preview`:

```text
common ancestor
+ current target head
+ current source head
→ structurally validated in-memory merged state
```

No temporary revision ID is fabricated. The candidate remains an uncommitted
state identified by the existing `weave-merge-preview-v1` token and its
`merged_root_hash`.

## Named target and canonical sources

The build-target definition is parsed from that candidate. Reserved target
metadata is never passed to the compiler. For each ordered program document,
Jacquard records:

- document name;
- stable root node ID;
- canonical-source SHA-256;
- canonical-source UTF-8 byte count.

Canonical sources are rendered in memory and written only to the validator's
private temporary directory. The directory is removed when validation returns.

## Compiler invocation

Validation uses the same authoritative frontend adapter as stored revisions:

```text
weavec --frontend program.wir source0.weave source1.weave ...
```

It does not invoke the backend, LLVM, a linker, a runtime archive, or the native
build command.

The response records the resolved compiler path and binary SHA-256. The compiler
hash participates in validation identity so replacing the compiler changes the
identity even when the candidate and sources are unchanged.

## Validation identity

`weave-merge-validation-v1` hashes:

```text
format
+ merge preview ID
+ prospective merged root hash
+ named target configuration
+ ordered document names and source hashes
+ compiler binary hash
```

The resulting `validation_id` identifies the exact candidate, source order,
target definition, and compiler executable that were checked. It is evidence,
not a reusable capability token: compiler-gated publication repeats validation.

## Bounded response

The public result contains:

- preview, ancestor, and both branch-head identities;
- merged root hash;
- named target and ordered source records;
- compiler path and SHA-256;
- availability, validity, return code, and timeout state;
- optional diagnostic text;
- bounded stdout and stderr;
- WIR SHA-256 and byte count, but not WIR contents.

Stdout and stderr are each limited to 8,192 characters. Truncation flags state
whether more output was produced. Temporary source and WIR files are not retained
or exposed.

## Compiler-gated publication

```text
branch_merge(
  project,
  target_branch,
  source_branch,
  preview_id = reviewed preview,
  validation_target = named target
)
```

When `validation_target` is present, publication performs this sequence:

1. recompute the current merge candidate;
2. reject a stale supplied preview ID;
3. resolve and render the named target from the candidate;
4. invoke `weavec --frontend`;
5. reject unavailable or failed validation;
6. use the validation's preview ID for merge publication;
7. atomically recheck both heads inside the SQLite write transaction;
8. publish the immutable two-parent merge revision.

This closes both races:

- a branch change before validation changes the preview ID;
- a branch change during or after validation fails the transactional head check.

The exact candidate that passed validation is therefore the only candidate that
can be published by that call.

## Failure codes

- `MERGE_CONFLICT`: the structural three-way merge is not clean;
- `STALE_MERGE_PREVIEW`: a supplied preview no longer describes current heads;
- `MERGE_VALIDATION_UNAVAILABLE`: no executable compiler could perform the gate;
- `MERGE_VALIDATION_FAILED`: the compiler rejected or timed out on the candidate;
- `NotFoundError`: the named target or one of its ordered source documents is
  absent from the prospective merged state.

Every failure leaves the target branch unchanged.

## Compatibility

`branch_merge` still permits calls without `preview_id` and
`validation_target`. Those calls retain atomic branch-head safety but do not prove
that the prospective combined program passes the compiler frontend.

Parallel agent work should use the complete preview, validation, and publication
sequence whenever a named target exists.
