# AGENTS.md

## Mandatory detailed guidance

Before changing this repository, read
[`docs/agent-development-rules.md`](docs/agent-development-rules.md) in full.
That document preserves the complete architectural, concurrency, validation,
layout, and change-protocol rules that previously lived in this file. Its rules
remain mandatory and are part of this agent contract.

For retained-artifact lifecycle work, also read
[`docs/artifact-retention-lifecycle.md`](docs/artifact-retention-lifecycle.md).

## Issue-closing pull-request gate

A pull request remains a draft while the issue it references has any
unimplemented acceptance criterion. A partial implementation may be committed
and tested in a draft, but it must not be described or marked as ready for
review.

A pull request remains a draft while any required CI job for its exact final head
is queued, running, cancelled, or red. Do not stop after starting CI. Wait for
all required jobs to reach a terminal result and inspect that result.

When CI is red, the work is unfinished. Diagnose the failure, fix the defect,
rerun the required checks, and continue until the exact final head is green.
Never treat a previously green head, a superseded run, or a locally passing
subset as final evidence.

Mark a pull request ready for review only when all of the following are true:

1. the pull request fully implements the referenced issue and its acceptance
   criteria;
2. the pull request body contains `Closes #<issue>` for that issue;
3. all required portable and packaged CI jobs pass on the exact final head;
4. the full final diff and commit structure have been reviewed;
5. the validation record in the pull request body matches the exact final head.

If any item is not true, keep working and keep the pull request in draft.

## Compatibility discipline

Internal modules and import paths are not compatibility commitments. Do not add
aliases, forwarding modules, duplicate paths, or deprecation shims unless an
explicit supported public compatibility requirement demands them. Migrate all
repository callers and remove obsolete internal paths in the same change.

