# AGENTS.md

[OodiHandbook](https://github.com/ahojukka5/OodiHandbook/blob/v0.1.0/index.qmd)
is the source of common rules. Follow the repository's explicitly adopted
immutable release (AUTH-003). Use [reviewed master guidance](https://github.com/ahojukka5/OodiHandbook/blob/master/index.qmd)
as a voluntary improvement target (AUTH-006). Local instructions provide
technical details and do not override the Handbook.

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

Follow Fast development in `~/dev/AGENTS.md`. The local test of the change is
the gate. A queued, running, or red GitHub job does not keep the pull request
in draft and is not the next task.

Mark a pull request ready for review only when all of the following are true:

1. the pull request fully implements the referenced issue and its acceptance
   criteria;
2. the pull request body contains `Closes #<issue>` for that issue;
3. the local test of the change has passed, and that command is recorded;
4. the full final diff and commit structure have been reviewed;
5. the validation record in the pull request body matches the exact final head.

If any item is not true, keep working and keep the pull request in draft.
Unfinished issue acceptance criteria or local validation remain a draft gate;
a queued or red remote GitHub run alone does not override Fast development.

## Compatibility discipline

Internal modules and import paths are not compatibility commitments. Do not add
aliases, forwarding modules, duplicate paths, or deprecation shims unless an
explicit supported public compatibility requirement demands them. Migrate all
repository callers and remove obsolete internal paths in the same change.
