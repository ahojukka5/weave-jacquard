# Contributing

Thank you for contributing to `weave-jacquard`.

This project explores an agent-native programming environment. Changes should
keep the core invariants explicit, deterministic, and covered by tests.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the validation suite before submitting changes:

```bash
python -m compileall -q src tests
ruff check .
pytest --cov=weave_frontend --cov-report=term-missing
```

## Commit rules

All commits must use Conventional Commit messages.

The topic line must:

- use the Conventional Commits format;
- describe one coherent change;
- be no longer than 72 characters;
- use the imperative mood where practical;
- not end with a period.

After the topic line, add a blank line and a one-to-three sentence summary.
The summary should explain what changed and why it changed.

When additional details are needed, add them as a bullet list after the summary.
Wrap all body text to fewer than 80 characters per line.

Example:

```text
feat: add semantic function merge

Merge independently edited functions by stable symbol identity and validate the
combined module before advancing the target branch.

- Reject incompatible edits to the same function.
- Preserve immutable parent revisions.
- Record both merge parents in revision history.
```

Common commit types include:

- `feat`: add user-visible behavior;
- `fix`: correct faulty behavior;
- `docs`: change documentation only;
- `test`: add or repair tests;
- `refactor`: restructure code without changing behavior;
- `perf`: improve performance;
- `ci`: change continuous integration;
- `build`: change packaging or build tooling;
- `chore`: perform repository maintenance.

## Pull requests

Keep pull requests focused on one topic. Explain the architectural effect of the
change and identify any invariants, interfaces, schemas, or design documents
that were added or changed.

Every pull request should include:

- tests for new behavior and regressions;
- deterministic output where serialization is involved;
- documentation for public APIs or architectural decisions;
- migration notes when persistent data changes;
- a clear description of validation performed.

## Architecture rules

Read `AGENTS.md` and `docs/architecture.md` before changing the data model,
revision semantics, grammar, validation rules, merge behavior, or public API.
Read `docs/single-node-concurrency.md`,
`docs/program-target-concurrency.md`, and
`docs/context-policy-concurrency.md` before changing direct branch-state writes.
Consult `docs/write-concurrency-audit.md` before adding a new mutating tool.

In particular:

- invalid AST mutations must be rejected atomically;
- committed revisions must remain immutable;
- branch heads must advance only after successful validation;
- every existing-branch mutation must publish from one captured base through a
  transactional compare-and-set branch update;
- prepared direct writes must reject stale `expected_revision_id` state;
- auxiliary persistent rows, operation payloads, revision links, and the branch
  update must commit or roll back together;
- merge must use a common base revision;
- merged states must be semantically validated;
- canonical rendering must remain deterministic;
- design context and contracts must be versioned with program state.
