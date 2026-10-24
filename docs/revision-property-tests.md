# Generated revision histories

`tests/test_revision_state_machine.py` uses Hypothesis to generate bounded
histories through the current workspace and metadata APIs. Each example creates
its own SQLite store, generates program/document creation, edits, batches,
current and historical forks, merges, reverts, context documents, tasks,
checkpoints, merge policies and test definitions, and tries stale writes and
invalid batches.

A separate reference model records branch heads and both revision parents from
operation outcomes. After every step the test checks the actual SQL rows against
that model, foreign keys and project ownership, historical row immutability,
snapshot and root hashes computed with independent JSON/SHA-256 code, and repeat
rendering. Rejected writes must preserve the complete SQL dump. The model does
not use production head or ancestry helpers to calculate its expected state.

The ordinary deterministic budget is 25 examples with up to 30 steps each:

```sh
python -m pytest -q tests/test_revision_state_machine.py
```

For deeper local exploration use 100 examples with up to 150 steps:

```sh
JACQUARD_EXTENDED_PROPERTIES=1 python -m pytest -q tests/test_revision_state_machine.py
```

Hypothesis shrinks failures to the generated operation sequence and prints a
versioned `@reproduce_failure` blob. Preserve a discovered production failure as
an ordinary targeted regression before changing production behavior. A selected
random seed can also be replayed with `--hypothesis-seed=<integer>`; retain the
Hypothesis version with that command. Native compiler and sandbox qualification
remain separate from these structural/revision properties.
