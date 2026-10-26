# Contributing

Common process rules come from the latest approved
[OodiHandbook](https://github.com/ahojukka5/OodiHandbook) tag (AUTH-007).
Reviewed master guidance may apply ahead of a tag (AUTH-006). Local instructions
provide repository technical facts within that authority.

Thank you for contributing to `weave-jacquard`.

## Mandatory detailed guidance

Read [`AGENTS.md`](AGENTS.md) and
[`docs/contributor-development-guide.md`](docs/contributor-development-guide.md)
before making changes. The detailed guide preserves the complete development,
commit, architecture, validation, and pull-request rules that previously lived
in this file. Those rules remain mandatory.

## Pull-request completion and CI gate

Keep a pull request in draft until it fully implements and closes its referenced
issue. Unfinished acceptance criteria stay in draft. Green CI for a partial
slice does not make the pull request ready for review. The pull request body
must contain `Closes #<issue>` only when every acceptance criterion is
implemented or the issue owner has explicitly removed it from scope.

Keep incomplete implementation or unmet acceptance criteria in draft.
After relevant local validation, open a reviewable PR and report the
exact final head, commands, results and limitations (ENG-008). A queued or red
non-required
GitHub run does not prevent review and does not by itself keep the pull request
in draft. Do not poll or repair CI unless requested.

Before an authorized rebase-merge, inspect the actual diff and review comments
and require every check enforced by an active ruleset to pass on that head
(ENG-007, ENG-018). Report a blocked required check; never bypass it.

## Compatibility discipline

Internal modules and import paths are not compatibility commitments. Do not add
aliases, forwarding modules, duplicate paths, or deprecation shims unless an
explicit supported public compatibility requirement demands them. Migrate all
repository callers and remove obsolete internal paths in the same change.
