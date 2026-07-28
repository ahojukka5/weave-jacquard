# Jacquard architecture

## 1. Thesis

A coding agent should not have to regenerate and reconcile complete source files.
Jacquard gives agents a versioned structural programming environment:

```text
DISCOVER → INSPECT → MUTATE → CHECKPOINT → PREFLIGHT → BUILD → TEST → MERGE
```

Jacquard owns stable syntax-tree identity, immutable revisions, transactional
publication, agent coordination, canonical source materialization, verified build
and test evidence, and merge admission. The authoritative Weave language
implementation and native compiler remains
[`weavec`](https://github.com/ahojukka5/weavec).

## 2. Authority boundaries

Jacquard is not a second compiler.

`weavec` owns:

- the accepted surface language;
- lowering to WIR;
- LLVM generation and optimization;
- runtime selection;
- target selection, object generation, linking, and native output.

Jacquard owns:

- stable node IDs and structural edits;
- canonical source and source maps;
- revision, branch, context, task, checkpoint, and policy history;
- compiler invocation bounds and protocol validation;
- build, test, candidate, attestation, and database-backup artifact integrity;
- aggregate retained-artifact accounting and publication quota admission;
- optimistic concurrency and merge publication;
- MCP application composition and exact public tool contracts.

Grammar examples inferred from the `weavec` correctness corpus are observational
guidance. `program_validate`, target validation, and compiler-backed merge
qualification remain authoritative.

## 3. Persistent state model

The core persistent graph is:

```text
project
├── branches ────────────────┐
├── immutable revisions ◄────┘
│   ├── parent1
│   ├── optional parent2
│   ├── compressed module snapshots
│   ├── ordered operation rows
│   └── referenced context documents
├── revisioned program documents
├── revisioned build and test definitions
├── revisioned policy and task context
└── external verified artifact stores
```

A branch is the only mutable pointer in the program graph. Revisions, snapshots,
operations, and content documents are immutable evidence.

SQLite schema version 3 enforces project-local parent and branch-head integrity,
unique operation order, foreign keys, and compressed snapshots. Startup refuses a
newer unsupported schema and checks existing data before migration.

Direct branch checkout remains an internal recovery primitive. It is exposed by
neither MCP nor the public `weave_jacquard.SExpressionWorkspace` facade. Public
historical work creates a branch at an immutable revision or publishes an
immutable revert.

## 4. Public application composition

The production MCP application is assembled from an ordered dependency graph of
capabilities. The graph currently covers:

- concurrent node, branch, target, and context operations;
- agent checkpoints and checkpoint timelines;
- build discovery;
- test definitions, strict runs, batches, and impact planning;
- virtual merge-candidate build and test execution;
- tested-merge attestations and revision evidence;
- revisioned task contracts and immutable reverts;
- target-authoritative policy and preflight;
- project agent status, merge queues, impact queues, and merge-train previews;
- resume snapshots and bounded revision reads;
- verified online database backup;
- aggregate artifact storage accounting and quota admission;
- content-derived runtime identity.

Composition produces three deterministic snapshots:

1. the capability manifest;
2. the complete MCP tool-contract manifest;
3. the application manifest binding capabilities, tool-manifest identity, tool
   count, and public configuration variables.

Every tool contract includes its name, description, input and output schemas,
annotations, icons, metadata, and a content-derived contract ID. The aggregate
manifest has its own content-derived identity. This manifest—not a hand-maintained
list in documentation—is the authoritative public surface.

Application composition isolates FastMCP registry access in one compatibility
boundary. A frozen `RuntimeConfig` and explicit `RuntimeServices` container own the
production workspace, SQLite connection, compiler bridge, executable discovery, and
shutdown lifecycle. The first capability installs those runtime-backed factories
before dependent modules are composed. Remaining dependent service caches are an
incremental migration boundary rather than owners of separate runtime roots.

## 5. Structural programming model

An S-expression is an ordered rooted tree. Every node has a stable ID independent
of source lines or byte offsets.

Agents normally use bounded local operations:

- inspect a local subtree;
- find nodes by structural properties;
- create one form or atom;
- update, move, wrap, or delete one node;
- apply one coherent bounded edit batch.

A single edit publishes one immutable revision. `node_apply_batch` applies 1–256
flat ordered operations in memory, validates once, writes one snapshot and ordered
audit rows, and advances the branch with one compare-and-set.

Bulk source import exists for migration and fixtures. It is bounded and parsed into
the same validated tree representation; it is not the normal agent-writing path.

Every structural publication enforces:

- valid node shapes and atom values;
- stable unique IDs;
- bounded depth, node count, and atom payloads;
- ordered children;
- cycle-free moves;
- deterministic canonical rendering.

Semantic completeness remains compiler authority.

## 6. Concurrency and publication

Existing-branch writes follow this pattern:

```text
read branch head
→ construct and validate candidate state
→ BEGIN IMMEDIATE
→ recheck expected head
→ publish all immutable consequences
→ conditional branch-head update
→ commit
```

No persistent auxiliary rows may survive a failed publication. Context documents,
operation payloads, revision-document links, snapshots, and branch movement commit
or roll back together.

Merge publication captures and rechecks both source and target heads. It writes one
two-parent revision and advances only the target branch.

SQLite uses WAL mode and an explicit 5,000 ms default busy timeout. Exhausted
`SQLITE_BUSY` or `SQLITE_LOCKED` waits become stable retryable `DATABASE_BUSY`
evidence. Jacquard does not replay a mutation inside the database layer: callers
must restart the application operation so optimistic reads and candidate state are
recomputed.

SQLite remains a single-writer database. Stable contention semantics make multiple
processes predictable; they do not turn the embedded store into a distributed
writer system.

## 7. Compiler and artifact boundary

Pinned committed-revision builds follow:

```text
immutable revision
→ canonical ordered .weave inputs and node maps
→ bounded final weavec process
→ validated compiler manifest and diagnostics
→ verified content-derived build directory
```

A successful build is admitted only when compiler identity, source order, requested
and reported target, output paths, protocol status, artifact hashes, and build-key
identity agree.

Virtual merge-candidate builds follow the same compiler and artifact rules but bind
their identity to:

- project and merge direction;
- common base and both branch heads;
- preview ID and merged-root hash;
- revisioned target definition;
- canonical candidate sources;
- compiler identity and output policy.

A structural preview is in memory and creates no synthetic revision. Explicit
candidate build and test operations may retain verified artifacts outside the
revision database. They remain bound to an exact virtual subject whose
`committed_revision_id` is null.

Stored committed-build and candidate-build manifests are admitted through a
bounded race-resistant regular-file reader before semantic or checksum
verification.

## 8. Sandboxed behavioral tests

Test definitions are revisioned program metadata. A test binds:

- a named build target;
- arguments and standard input;
- expected exit status, stdout, and stderr;
- timeout, memory, output, and file-size ceilings.

Execution requires the canonical Bubblewrap sandbox and `prlimit`. Sandbox
admission proves process-creation denial and reports the exact effective policy and
binary identities. Test runs retain immutable manifests plus hashed stdout and
stderr bytes. Bounded output-page tools expose retained streams without loading
them completely.

Explicit batches run a caller-ordered bounded set at one revision. Test-impact
planning selects tests from changed documents and revisioned target relationships.
Merge impact can apply the same logic to an exact virtual candidate.

Current sandbox evidence is intentionally explicit about protections not supplied
by the backend, including stronger aggregate cgroup accounting and a dedicated
seccomp policy.

## 9. Merge qualification and publication

The merge pipeline is layered:

```text
stable-ID preview
→ directional document and target impact
→ affected target and test selection
→ compiler and sandbox qualification
→ target-authoritative policy evaluation
→ exact preflight identity
→ transactional publication
```

A preview binds project, direction, common base, target head, and source head.
Directional impact compares the target with the prospective merged state, so it
reports only consequences introduced by the source branch.

Revisioned target policy controls required replay, affected-target coverage,
uncovered-document overrides, and bounded compiler fanout. Policy lookup follows
first-parent target history. A source branch can propose a different policy but
cannot weaken the target.

Virtual-candidate tests retain qualification evidence without publishing a merge.
After publication, a tested-merge attestation proves that the committed revision
has exactly the qualified candidate root and both qualified parents. The
attestation does not claim complete semantic coverage, human approval, or
production readiness.

Both heads are checked again inside the write transaction. A head change before
replay changes preflight identity; a head change during publication fails the
conditional update.

## 10. Agent coordination

Jacquard treats multi-agent development as revisioned engineering work rather than
an external conversation convention.

The public capability graph includes:

- task contracts with scope and acceptance evidence;
- scoped edit enforcement;
- agent checkpoints and timelines;
- project-wide agent status;
- merge queues and impact-aware ordering;
- selected preflight batches;
- merge-train previews;
- resume snapshots containing the evidence needed to continue work;
- immutable reverts rather than destructive branch rewinds.

These objects bind work to exact revisions and tool-produced evidence. They do not
replace human review policy; they make the state reviewed by humans and agents
reproducible.

## 11. Revision evidence and recovery

Revision evidence connects immutable program history to external artifacts:

- build identities and compiler hashes;
- test-run and batch manifests;
- virtual-candidate qualifications;
- tested-merge attestations;
- task contracts and checkpoints;
- merge and revert operations.

Retained JSON families use explicit byte ceilings and reject symlinks,
non-regular files, path replacement during open, invalid UTF-8, invalid JSON, and
limit overflow before normal verification.

Revert is a new immutable revision whose state matches an earlier selected state.
It preserves intervening history and produces normal publication evidence. Resume
snapshots summarize pinned work state; they do not mutate branches.

The production server can create and reverify content-derived online SQLite
backups. Restore is deliberately offline and publishes only to a new absent path.
Database backups join builds, tests, qualifications, and attestations in the shared
aggregate retained-artifact quota. Artifact reconciliation, retention, guarded
garbage collection, and remote recovery replication remain operator capabilities
to implement.

## 12. Resource limits

Jacquard uses explicit ceilings rather than assuming inputs are small.

Structural limits cover:

- imported source bytes;
- tree depth and node count;
- one atom and aggregate atom payloads;
- canonical and annotated rendering.

Compiler limits cover:

- process lifetime;
- stdout and stderr capture;
- compiler manifest and diagnostics protocols;
- retained trace count, individual size, and aggregate size.

Artifact metadata limits cover committed builds, virtual-candidate builds, test
runs, test batches, virtual-candidate qualifications, tested-merge attestations,
and verified database backups. The production composition also enforces one
optional aggregate retained logical-byte ceiling across all seven publishers.

Grammar guidance independently bounds directory enumeration, corpus files and
bytes, forms, relationships, example rendering, diagnostics, query size, and
response fanout. Truncation is returned as evidence and never changes compiler
language authority.

Live SQLite database size, temporary staging blocks, and physical filesystem
allocation remain separate operator policy.

## 13. Qualification

The repository has one fail-closed qualification entry point:

```text
scripts/qualify.sh python
scripts/qualify.sh native
scripts/qualify.sh full
```

The runner owns compilation, Ruff, sandbox admission, pytest selection, skip
rejection, coverage, JUnit validation, trace contracts, environment identity,
compiler and sandbox binary hashes, completion evidence, and checksums.

GitHub workflows only acquire prerequisites, invoke the same runner, and upload the
completed evidence directory. Evidence is staged and published atomically; a
partial or failed run does not appear as a successful qualification directory.

`full` is the release-strength gate. It requires the final `weavec`, the complete
MCP environment, the strict sandbox, zero skipped tests, and all required protocol
and native traces.

## 14. Determinism

The same validated state, compiler identity, target, and options produce the same
canonical inputs and content-derived build key.

Merge identities are layered:

- same merge direction and heads → same preview ID;
- same preview and target graph → same impact identity;
- same candidate, targets, compiler, and policy → same validation evidence;
- same policies and complete qualification set → same preflight identity;
- same qualified candidate and committed two-parent state → same attestation input.

Only final user-facing `weavec` is part of the public compiler contract. Bootstrap
stages must not leak into Jacquard's API.

One process captures supported runtime configuration and executable discovery once.
Every production service rooted in that process therefore observes the same
database, artifact roots, compiler selection, sandbox selection, and quota policy.
Applying configuration changes requires a new process and produces new runtime
identity evidence.

## 15. Remaining boundaries and next milestones

The highest-value remaining work is:

1. **Runtime service-graph completion** — migrate dependent module-local caches into
   typed container fields, add explicit construction phases, and replace the
   remaining import-time service adaptation without changing MCP contracts.
2. **Database and artifact integrity** — complete snapshot and root-hash
   reconstruction, artifact reachability reconciliation, and bounded catalog
   evidence.
3. **Retention and storage operations** — explicit dry-run deletion plans, guarded
   garbage collection, quarantine recovery, temporary/physical-space policy, and
   live SQLite database-size policy.
4. **Compiler capability contract** — consume a machine-readable grammar,
   capability, target, and language-version registry from `weavec` and remove
   observational corpus dependence.
5. **Module interfaces and incremental compilation** — define revisioned interface
   objects and dependency hashes, then measure real multi-module workloads before
   introducing module caches.
6. **Sandbox strengthening** — add platform-supported aggregate cgroup and seccomp
   evidence without weakening the canonical fail-closed sandbox contract.
7. **Scale** — evaluate storage deduplication and a database architecture beyond
   SQLite only after measured workloads justify the complexity.

More MCP convenience tools are not the current priority. Jacquard already has a
broad public capability graph; the next phase is to complete explicit runtime
composition, operations, storage, and compiler integration with the same rigor as
its revision and qualification contracts.
