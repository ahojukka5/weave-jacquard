# Contributing

Thank you for contributing to `weave-jacquard`.

## Mandatory detailed guidance

Read [`AGENTS.md`](AGENTS.md) and
[`docs/contributor-development-guide.md`](docs/contributor-development-guide.md)
before making changes. The detailed guide preserves the complete development,
commit, architecture, validation, and pull-request rules that previously lived
in this file. Those rules remain mandatory.

## Pull-request completion and CI gate

Keep a pull request in draft until it fully implements and closes its referenced
issue. Green CI for a partial slice does not make the pull request ready for
review. The pull request body must contain `Closes #<issue>` only when every
acceptance criterion is implemented or the issue owner has explicitly removed
it from scope.

Do not stop after starting CI. Wait until every required job for the exact final
head reaches a terminal result.

- If a required job is queued or running, keep the pull request in draft and
  continue checking.
- If a required job is red or cancelled, the work is unfinished. Diagnose the
  failure, fix it, rerun the checks, and continue until they are green.
- Do not rely on a green run from a superseded commit.
- Do not mark a pull request ready while validation evidence is incomplete.

A pull request may be marked ready for review only after:

1. it fully closes the issue named in its body;
2. its exact final head passes compileall, Ruff, the full required pytest suite,
   and every required packaged/native qualification;
3. all evidence uploads and required workflow finalization steps succeed;
4. its final diff and commit history have been reviewed and cleaned up;
5. its description records validation from that exact final head.

When any condition is unmet, keep working rather than handing off an incomplete
pull request.
