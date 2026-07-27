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
`docs/program-target-concurrency.md`,
`docs/context-policy-concurrency.md`,
`docs/reproducible-branch-creation.md`,
`docs/agent-resume-snapshot.md`,
`docs/agent-checkpoints.md`,
`docs/agent-checkpoint-timeline.md`,
`docs/project-agent-status.md`,
`docs/project-merge-catalog.md`,
`docs/project-merge-queue.md`,
`docs/project-merge-impact-queue.md`,
`docs/selected-merge-preflight-batch.md`, and
`docs/selected-merge-train-preview.md` before changing branch writes, fork
semantics, one-call orientation reads, handoff protocols, checkpoint
supervision, project-wide agent status, project merge catalogs and queues,
non-compiling merge-impact review, compiler-backed selected preflight
orchestration, or order-aware virtual merge simulation.
Consult `docs/write-concurrency-audit.md` before adding a new mutating tool.

In particular:

- invalid AST mutations must be rejected atomically;
- committed revisions must remain immutable;
- branch heads must advance only after successful validation;
- every existing-branch mutation must publish from one captured base through a
  transactional compare-and-set branch update;
- prepared direct writes and current-head forks must reject stale reviewed state;
- historical forks must select one project-owned immutable revision explicitly;
- auxiliary persistent rows, operation payloads, revision links, and the branch
  update must commit or roll back together;
- a revision-pinned composite read must not mix programs, targets, policy,
  context, operations, checkpoints, or history from a newer branch head;
- bounded composite reads must expose totals, returned counts, and truncation;
- checkpoint publication must preserve the captured program root hash;
- checkpoint readers must verify scope, format, structure, and content hash;
- historical checkpoint resolution must follow only the selected revision's
  first-parent history and must never borrow a later handoff;
- checkpoint resume arguments must remain pinned to the publishing revision;
- sparse checkpoint paging must bound both returned checkpoints and revisions
  scanned;
- checkpoint page continuation must identify the exact first unscanned immutable
  revision rather than a mutable offset;
- checkpoint comparison endpoints must be exact revisions that published
  checkpoints;
- checkpoint list deltas must remain structural evidence and must not infer
  completion, resolution, invalidation, ancestry, or chronology;
- project-wide branch pages must use one exact catalog of branch names and head
  revisions, and stale catalogs must be rejected rather than mixed;
- project branch catalogs and page sizes must have explicit fanout bounds;
- per-branch checkpoint discovery must have an independent first-parent scan
  bound and distinguish incomplete search from complete no-checkpoint evidence;
- project agent status must not infer inactivity, correctness, completion,
  blockage, or review readiness from timestamps, checkpoint lag, status labels,
  or program root hashes;
- project merge orchestration must reuse `ProjectMergeCatalogService` for lexical
  branch membership, target/source partitioning, fanout enforcement, and catalog
  hashing rather than querying branches or rebuilding catalog identities itself;
- project merge queues must bind one exact target head and every source head in a
  stable catalog, rejecting source or target changes rather than mixing previews;
- merge-queue pages must independently bound source count, checkpoint scanning,
  conflicts, and changed-document evidence while reporting totals and truncation;
- merge-queue `mergeable` values must mean structural preview success only and
  must not imply policy admission, target coverage, compiler validation,
  preflight identity, publication-head stability, or human readiness;
- merge-queue lexical ordering must remain deterministic pagination and must not
  be interpreted as priority, urgency, age, quality, checkpoint freshness, or
  readiness;
- merge-impact queues must resolve target and source policy at their exact
  catalog revisions; target policy is authoritative and source policy cannot
  weaken it;
- structurally conflicted sources must stop before target-impact analysis;
- merge-impact pages must independently bound affected targets and every returned
  coverage-document collection while preserving totals and continuation;
- named-target coverage classes and uncovered-document override evidence must
  remain structural policy inputs and must not imply compiler correctness,
  preflight identity, publication-head stability, human approval, or readiness;
- non-compiling merge-impact review must never silently run builds or affected-
  target validation; compiler-backed admission remains an explicit preflight
  stage;
- selected preflight batches must accept only an explicit bounded unique source
  list and must preserve caller order without selecting, ranking, or expanding it;
- uncovered-document overrides in a selected batch must be an explicit subset of
  selected sources and remain subject to exact target-policy authority;
- selected preflight batches must verify the complete exact project merge catalog
  before and after compiler work, including unselected branches, and must reject
  catalog drift rather than return partial stale evidence;
- per-source domain errors in a selected batch must remain independent evidence,
  while catalog-staleness errors must invalidate the whole batch identity;
- selected compiler-backed batch results must bound target-validation and
  document evidence while preserving totals, truncation, replayable full
  preflight, and guarded publication arguments;
- selected preflight batches must publish no merge and advance no branch;
  `ready_for_publication` remains exact guarded evidence requiring explicit
  `branch_merge` publication;
- selected merge-train previews must accept only an explicit bounded unique
  source list and preserve caller order without selecting, ranking, or expanding
  it;
- selected merge-train previews must verify the complete exact project merge
  catalog before and after simulation, including unselected branches, and reject
  catalog drift rather than return stale train evidence;
- every train step must use the source's real common ancestor with the original
  committed target head, compose against the accumulated in-memory virtual target,
  and semantically validate each clean result;
- merge-train evidence must distinguish consistent clean/conflict outcomes from
  order-introduced and order-removed conflicts, and must expose later redundant
  sources as `no_changes` rather than inventing a new committed revision;
- merge-train simulation must stop at the first unresolved conflict because no
  valid virtual target exists for later steps;
- selected merge-train previews must run no compiler, preflight, persistent write,
  or merge publication, and virtual target roots must never be treated as
  committed revisions;
- only the first clean train step may reuse the current catalog's normal preview;
  after every real merge publication, callers must refresh the complete catalog
  and preflight the next source against the new target head;
- merge-train source order is structural caller input and must not be interpreted
  as priority, urgency, quality, business value, or human readiness;
- merge must use a common base revision;
- merged states must be semantically validated;
- canonical rendering must remain deterministic;
- design context, contracts, and agent handoffs must be versioned with program
  state.
