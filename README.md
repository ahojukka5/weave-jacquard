# Jacquard

**Jacquard is the agent-native programming environment for Weave.** Coding
agents edit a versioned S-expression tree through structural MCP operations
instead of repeatedly replacing complete source files.

The name refers to the Jacquard loom: a programmable mechanism that turns a
stored pattern into coordinated weaving operations. Agents modify the program
pattern, Jacquard preserves structure, history, evidence, and publication rules,
and `weavec` turns canonical sources into native programs.

Repository and Python distribution: **`weave-jacquard`**  
Public Python namespace: **`weave_jacquard`**  
Primary executables: **`weave-mcp`** and **`weave-build`**

## What Jacquard owns

Jacquard provides:

- stable node identities and bounded structural edits;
- immutable revisions, parallel branches, and compare-and-set publication;
- deterministic canonical source and UTF-8 node maps;
- revisioned design context, merge policy, task contracts, and test definitions;
- agent checkpoints, timelines, project status, queues, merge-train previews, and
  resume snapshots;
- compiler-backed validation and verified committed or virtual-candidate builds;
- strict sandboxed test runs, explicit batches, and affected-test planning;
- stable-ID merge preview, impact, qualification, preflight, and publication;
- tested-merge attestations, revision evidence graphs, and immutable reverts;
- content-derived MCP tool and application manifests;
- bounded artifact metadata, grammar-corpus indexing, compiler I/O, and
  qualification evidence.

Jacquard is not another compiler. The user-facing
[`weavec`](https://github.com/ahojukka5/weavec) compiler owns the Weave language,
surface lowering, WIR, LLVM generation and optimization, runtime selection,
target output, object generation, and linking.

## Architecture in one view

```text
agent or editor
      │
      ▼
content-derived MCP application contract
      │
      ▼
versioned structural workspace
      ├── program trees with stable node IDs
      ├── branches and immutable revisions
      ├── context, policy, tasks, checkpoints, and tests
      └── ordered audit operations
      │
      ├──────────────► exact virtual merge candidate
      │                       │
      ▼                       ▼
pinned committed build   candidate build and tests
      │                       │
      └──────────┬────────────┘
                 ▼
       bounded final `weavec`
                 │
                 ▼
     verified artifacts and evidence
```

A branch is the only mutable pointer in the program graph. Existing-branch writes
recheck the expected head inside the same SQLite transaction that publishes all
immutable consequences.

The supported public workspace is `weave_jacquard.SExpressionWorkspace`. Direct
historical checkout is intentionally absent. Create a branch at an immutable
revision or publish an immutable revert instead of destructively moving a branch.

See [the architecture](docs/architecture.md) for the complete ownership and
publication model.

## Installation

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the stdio MCP server:

```bash
weave-mcp
```

The public Python API begins with:

```python
from weave_jacquard import SExpressionWorkspace

with SExpressionWorkspace("weave.db") as workspace:
    workspace.initialize("demo")
```

## Configuration

Common environment variables are:

| Variable | Purpose |
|---|---|
| `WEAVE_DB_PATH` | SQLite workspace path |
| `WEAVEC_BIN` | final `weavec` executable |
| `WEAVEC_SOURCE_ROOT` | optional correctness corpus for `grammar_help` |
| `WEAVE_BUILD_ROOT` | committed build artifact root |
| `WEAVE_MERGE_BUILD_ROOT` | virtual-candidate build root |
| `WEAVE_TEST_RUN_ROOT` | committed test-run root |
| `WEAVE_TEST_BATCH_ROOT` | aggregate committed test-batch root |
| `WEAVE_MERGE_TEST_RUN_ROOT` | virtual-candidate qualification root |
| `WEAVE_MERGE_ATTESTATION_ROOT` | tested-merge attestation root |
| `WEAVE_BWRAP` | explicit Bubblewrap executable |

`WEAVEC_BIN` may be omitted when `weavec` is available on `PATH`.
`WEAVEC_SOURCE_ROOT` affects observational grammar help only; compiler validation
remains authoritative.

The exact public configuration-variable set is bound into the application
manifest.

## Structural editing workflow

A normal agent workflow is:

```text
project_initialize
→ program_create
→ grammar_help for unfamiliar forms
→ node_inspect / node_find
→ single-node edits while exploring
→ node_apply_batch for one coherent known structure
→ program_validate
→ checkpoint and task evidence
```

Every successful single-node edit creates one immutable revision.
`node_apply_batch` accepts 1–256 flat ordered structural operations, supports
temporary aliases for nodes created earlier in the request, validates the final
tree once, and publishes one revision or nothing.

Bulk `program_import` exists for migration and fixtures. It is bounded and parsed
into the same validated tree representation; normal agents should prefer
structural operations.

## Build and test workflow

Committed-revision work is pinned to one exact immutable state:

```text
build_target_set / test_target_set
→ target or test-impact selection
→ build_target_validate
→ build_target_build or test_run / test_batch_run
→ bounded diagnostics or output inspection
→ revision evidence
```

A successful build binds:

- revision and root hashes;
- ordered source and node-map hashes;
- requested target;
- final compiler binary hash;
- compiler manifest and diagnostics protocols;
- every retained artifact path and SHA-256 hash.

Behavioral tests bind a revisioned build target, arguments, standard input,
expected exit status and streams, and explicit timeout, memory, output, and
file-size ceilings. Execution requires the canonical Bubblewrap and `prlimit`
sandbox policy.

## Merge workflow

Protected merge publication is evidence-driven:

```text
branch_merge_preview
→ branch_merge_impact
→ affected target and test selection
→ virtual-candidate build and sandboxed tests
→ tested qualification evidence
→ branch_merge_preflight
→ review publication arguments
→ branch_merge
→ tested_merge_attest
```

Target-branch policy governs admission. An incoming branch may carry a different
policy, but it cannot weaken the target.

A structural preview remains in memory and creates no synthetic revision. Explicit
candidate builds and tests may retain verified artifacts bound to the exact
virtual subject. After publication, a tested-merge attestation proves that the
committed two-parent revision exactly matches the qualified candidate state.

Preflight evidence is not a bearer token. Publication recomputes current policy,
heads, impact, and required qualification, then checks both heads inside the
write transaction.

## Parallel-agent workflow

Jacquard can represent agent work directly:

```text
task contract
→ scoped branch edits
→ checkpoints and timeline
→ project agent status
→ impact-aware merge queue
→ selected preflight batch
→ merge-train preview
→ publication or immutable revert
→ resume snapshot
```

These capabilities bind coordination to exact revisions and evidence. They do not
replace human review policy; they make the reviewed state reproducible.

## Concurrency and retry behavior

SQLite runs in WAL mode with an explicit 5,000 ms default busy timeout. Exhausted
writer contention is returned as stable retryable evidence:

```json
{
  "code": "DATABASE_BUSY",
  "message": "database remained busy or locked for the configured timeout",
  "node_id": null,
  "retryable": true,
  "busy_timeout_ms": 5000
}
```

Retry the complete application operation so branch heads and optimistic
expectations are read again. Do not replay only the final SQL statements.

## MCP application contract

The public server is composed from an ordered capability graph. Composition
captures complete registered tool contracts and creates:

- one content-derived ID per tool contract;
- an aggregate tool-manifest ID;
- an application ID binding capability order, tool-manifest identity, tool count,
  and configuration variables.

The generated manifest is the authoritative tool inventory. Documentation groups
capabilities by workflow and intentionally does not duplicate every live tool
schema by hand.

## CLI

`weave-build` exposes revision-pinned target and artifact operations, for example:

```bash
weave-build --db weave.db target-set demo application main.weave \
  --source library.weave
weave-build --db weave.db target-validate demo application
weave-build --db weave.db target-build demo application
weave-build --db weave.db get <build-id>
```

Failures are emitted as structured JSON on stderr with exit status 2.

## Qualification

Jacquard has one fail-closed qualification runner:

```bash
bash scripts/qualify.sh python
WEAVEC_BIN=/absolute/path/to/weavec bash scripts/qualify.sh native
WEAVEC_BIN=/absolute/path/to/weavec bash scripts/qualify.sh full
```

The runner owns compilation, Ruff, sandbox admission, pytest selection, skip
rejection, coverage, JUnit validation, protocol and native trace contracts,
environment identity, binary hashes, completion evidence, and checksums.

`full` is the release-strength gate. A successful evidence directory is published
only after all selected work and checksums complete.

## Resource safety

Explicit ceilings cover:

- source size, tree depth, node count, and atom payloads;
- canonical and annotated rendering;
- compiler process lifetime and captured output;
- compiler protocol files;
- retained build, candidate, test, qualification, and attestation manifests;
- grammar-corpus enumeration, bytes, index size, example rendering, diagnostics,
  query size, and response fanout;
- qualification trace count, individual size, and aggregate size.

Unsafe retained files, including symlinks and non-regular files, are rejected
before JSON decoding or semantic verification.

## Documentation

- [Architecture](docs/architecture.md)
- [Application composition](docs/application-composition.md)
- [Qualification](docs/qualification.md)
- [Structural resource limits](docs/structural-resource-limits.md)
- [Grammar corpus limits](docs/grammar-corpus-limits.md)
- [Database concurrency](docs/database-concurrency.md)
- [Database integrity](docs/database-integrity.md)
- [Write-concurrency audit](docs/write-concurrency-audit.md)
- [Transactional structural edits](docs/edit-transactions.md)
- [Revisioned merge policy](docs/merge-policy.md)
- [One-call merge preflight](docs/merge-preflight.md)
- [Merge candidate validation](docs/merge-validation.md)
- [Verified stored-build discovery](docs/build-discovery.md)
- [Compiler bridge](docs/compiler-bridge.md)
- [Revisioned build targets](docs/build-targets.md)
- [Snapshot storage](docs/snapshot-storage.md)
