# AGENTS.md

## Purpose

Jacquard is the agent-native programming environment, revision store, and MCP
server for Weave. The central object is a versioned program tree. Textual
`.weave` source is a deterministic view, not the primary editing surface.

## Architectural rules

1. **Never publish invalid program state.** A failed single edit, batch, or
   compiler-gated merge must not advance a branch head or leave partial audit
   rows.
2. **Published revisions are immutable.** A correction creates a new revision.
3. **Use stable semantic IDs.** Do not target source lines or formatting.
4. **Use the smallest coherent write unit.** Use one-node tools while exploring
   or repairing. A known local structure may use a bounded flat transaction of
   ordinary node operations. Never require a nested replacement AST.
5. **Keep batches bounded and auditable.** Every sub-operation must retain an
   ordered audit row, while the complete batch publishes as one revision or
   rolls back.
6. **Use optimistic concurrency for prepared edits.** Pass the expected base
   revision when a single-node mutation or batch was planned from a specific
   branch head. Every structural write must still compare-and-set its captured
   base when the expectation is omitted.
7. **Keep historical reads revision-consistent.** Once an exact immutable
   revision is selected, render, search, inspect, source-list, target, build,
   and diff reads must not silently mix in branch-head program state.
8. **Larger reads are acceptable.** Inspection may return a local subtree or
   complete source rendering when it helps an agent understand context.
9. **Do not duplicate the Weave grammar.** `weavec` is authoritative. Grammar
   help is derived from its source corpus and completed programs are validated
   by its frontend.
10. **Target policy governs admission.** The current target branch's first-parent
    policy is authoritative. A source branch policy is visible review evidence
    but must never weaken the target through merge.
11. **Preflight independent work before publication.** Reviewed parallel-agent
    merges should use `branch_merge_preflight`, inspect policy, directional
    impact, uncovered documents, and every affected surviving target, then
    publish with the returned arguments.
12. **Context is versioned.** Interfaces, contracts, invariants, policies, and
    design documents used by an agent must be reproducible from its base
    revision.
13. **Rendering is deterministic.** Identical database state and renderer version
    must produce byte-identical canonical source.
14. **Discover builds through verification.** A build-directory name is never
    build evidence. Discovery must remain bounded, verify each scanned manifest
    and artifact through the `build_get` admission path, and return only compact
    project-matching summaries.
15. **SQLite is the prototype truth store.** Avoid adding a distributed database
    until measurements require it.

## Node identity

- New lists and atoms receive stable `n_*` IDs.
- Editing an atom or moving a node preserves its ID.
- Copying or creating a node gives it a new ID.
- Batch aliases are temporary names for stable IDs created in that transaction.
- Annotated source may display IDs, but canonical program meaning does not depend
  on them.
- Merge, diff, preview, impact, preflight, policy, and MCP mutations target IDs or
  immutable revision identities, never line numbers.

## Historical read consistency

`node_inspect`, `program_render`, and `node_find` default to the selected branch
head. When `revision_id` is supplied, every returned program value, parent,
position, rendering, and match must come from that exact project-owned immutable
revision.

Historical read responses must report both:

- `revision_id`, the state actually read;
- `branch_head_revision_id`, the selected branch head at read time.

`revision_is_branch_head` must state whether they are equal. An explicit revision
does not need to remain reachable from the selected branch, but it must belong to
the project. The selected branch must exist so its current head can be reported.

`program_render` may extend its existing result object with this metadata.
`node_find` must preserve its compatibility `result` list and expose revision
metadata beside that list in the MCP response envelope, including when no nodes
match. Historical reads are non-mutating and must never check out a revision.

## Structural writes

Single-node tools are the default for uncertain work. They create or change one
form, atom, edge, or location and publish one revision per successful call.

Every single-node mutation must capture one branch head, load and mutate that
exact immutable state, and publish through a conditional branch-head update.
Prepared calls accept `expected_revision_id`; stale expectations fail before
mutation. Calls without an expectation remain race-safe and return the captured
`base_revision_id` after successful publication. A concurrent branch advance at
any point before commit must return `STALE_BRANCH_HEAD` and roll back the revision,
snapshot, operation row, and branch update together.

`node_apply_batch` is allowed for one coherent known structure. It must remain:

- a flat ordered list of existing structural operation kinds;
- bounded to a documented maximum;
- limited to one document and one pinned branch head;
- structurally validated before publication;
- one immutable revision with ordered per-operation audit rows;
- fully rolled back on any operation or stale-head failure.

Do not turn the batch tool into source replacement, a nested AST upload, an
unbounded request, or a way to bypass validation. Neither a single-node call nor
a batch may silently replay stale work on a newer branch head.

## Revisioned merge policy authority

`merge_policy_set` publishes one immutable policy revision directly on the
selected branch. Policy state is stored as a project-scoped immutable context
document referenced by a `set_merge_policy` operation. It must not become a
mutable global setting, an environment variable, or a compiler-source document.

`merge_policy_get` resolves the latest policy by walking first-parent history
from the selected branch head or exact project revision. Historical policy must
remain reproducible.

The current target policy controls:

- whether preflight replay is required;
- whether all affected surviving targets must validate;
- whether uncovered-document overrides are allowed;
- the affected-target compiler fanout ceiling.

The source branch policy is returned for transparency. Different policy hashes
must set `source_policy_ignored=true`, and the target policy must remain the only
admission authority. A policy can be loosened only by publishing a new policy
revision directly on the target branch. That branch-head change must invalidate
older preview and preflight evidence.

No configured policy must preserve legacy merge compatibility. Configuring a
policy must not change database schema, compiler protocols, stored build keys, or
source-language behavior.

## Merge preflight and publication

`branch_merge_preflight` is the default review boundary. It must compose the
current exact-candidate merge layers rather than introduce a parallel merge
implementation:

- target-authoritative and source-visible policy resolution;
- stable-ID three-way preview;
- directional named-target impact;
- candidate coverage analysis;
- complete affected-target frontend validation.

Preflight is read-only. It must create no revision, branch update, audit row,
build manifest, executable, retained WIR, or compiler artifact. Its deterministic
identity must bind policy hashes, source-policy disposition, merge direction,
exact preview and merged root, impact summary state, validation-set identity,
and uncovered-document policy.

The public impact list must remain bounded and explicitly report truncation. Any
truncation is presentation-only: the complete internal target graph still drives
the bounded validation set.

A preflight response is evidence, not authority. It may return
`publication_tool` and exact `publication_arguments`, including `preflight_id`,
but publication must resolve current policies, recompute preflight, compare
identity, enforce readiness, and then write. Never add a token that allows an old
preflight to bypass policy or compiler revalidation.

When exact preflight is recomputed successfully, publication may reuse that
single validation set before the same transactional branch-head check. Do not
launch a redundant second compiler fanout for the identical candidate.

## Merge preview, impact, and validation layers

`branch_merge_preview` is read-only. Its deterministic token must bind the
project, merge direction, common ancestor, target head, and source head. A clean
preview may report compact consequences but must never publish a snapshot or
advance a branch. A conflict preview must return exact conflict paths without
throwing away the reviewed head identities.

`branch_merge_impact` must compare the current target state with the prospective
merged state. It reports only consequences introduced by merging the source into
that target, not edits already present on the target branch. It must classify
added, removed, modified, and source-affected named targets deterministically and
paginate public target entries.

Target coverage must be computed from target definitions that survive in the
candidate. A removed target cannot hide a changed source document from
`uncovered_changed_documents`.

`branch_merge_validate` must validate one exact candidate target through
`weavec --frontend` without creating a revision or retained build artifact.

`branch_merge_validate_affected` must:

- validate every affected target that survives in the candidate;
- skip and report removed targets;
- use deterministic target-name order;
- keep compiler fanout bounded by both global and effective target policy limits;
- bind the effective limit into validation-set identity;
- aggregate every pass, rejection, and unavailable result;
- perform zero compiler work when uncovered documents block the candidate;
- record any explicit uncovered-document override.

A validation or validation-set response is evidence, not a bearer token.
Publication must repeat the selected gate and use that candidate's preview ID.
Compiler unavailability, compiler rejection, uncovered-document policy failure,
policy violation, merge conflict, stale preflight, or stale preview state must
leave the target branch unchanged.

Both reviewed branch heads must be rechecked inside the same SQLite write
transaction that publishes the merge. Any mismatch must return
`STALE_MERGE_PREVIEW` and leave the target branch and audit tables unchanged.
Direct merges without preview or validation remain supported only when the
effective target policy permits them; they must still capture and atomically
recheck both current heads.

## Verified build discovery

`build_list_page` is the recovery path when an agent no longer has a build ID.
It must not become an unverified directory listing or a mutable database catalog.

Catalog membership is limited to direct non-symlink build-ID directories with a
regular non-symlink manifest. Membership and lexical order are bound into a
`catalog_id`. Passing that identity on continuation must reject additions or
removals with `STALE_BUILD_CATALOG`.

Each request may scan at most 200 catalog members. Every scanned member must pass
the same manifest, path-containment, regular-file, and checksum verification used
by `build_get` before it can appear in `builds`.

Discovery must:

- return only compact summaries matching the requested project and filters;
- count but omit valid foreign-project and nonmatching builds;
- return malformed or corrupt members only as rejected build IDs and error codes;
- keep absolute artifact paths, raw compiler output, and mapped diagnostics out of
  the list response;
- preserve `build_get` as the detailed manifest and artifact-path boundary;
- allow sparse or empty pages while still advancing the lexical scan cursor.

The build-root catalog is live. A caller that requires stable multi-page
membership must replay `catalog_id`; a caller that intentionally omits it accepts
the current catalog on each page. Filesystem modification times must not be used
as immutable build chronology.

## Grammar and validation

The generic S-expression layer validates tree integrity:

- valid node shape;
- unique IDs;
- ordered children;
- legal atom values;
- no move cycles.

Do not add a second handwritten copy of the surface grammar. The MCP
`grammar_help` index reads `weavec/test/correctness/surface`. The
`program_validate`, `build_target_validate`, `branch_merge_validate`,
`branch_merge_validate_affected`, and `branch_merge_preflight` paths render
canonical source and invoke `weavec --frontend` where semantic validation is
required.

A later machine-readable grammar registry in `weavec` should replace corpus
inference without changing the public MCP API.

## Code layout

- `src/weave_frontend/service.py`: grammar-neutral revision and merge mechanics.
- `src/weave_frontend/sexpr.py`: generic S-expression nodes and rendering.
- `src/weave_frontend/sexpr_service.py`: historical single-node implementation.
- `src/weave_frontend/concurrent_sexpr.py`: race-safe public node mutations.
- `src/weave_frontend/mcp_concurrent_nodes.py`: production node-tool registration.
- `src/weave_frontend/batch_edit.py`: bounded transactional structural edits.
- `src/weave_frontend/revision_reads.py`: exact-revision render and node search.
- `src/weave_frontend/revision_diff.py`: bounded stable-node revision diffs.
- `src/weave_frontend/build_discovery.py`: verified stored-build catalog pages.
- `src/weave_frontend/merge_preview.py`: deterministic two-phase merge previews.
- `src/weave_frontend/merge_impact.py`: named-target and coverage impact analysis.
- `src/weave_frontend/merge_validation.py`: one exact-candidate compiler validation.
- `src/weave_frontend/merge_validation_set.py`: complete affected-target gate.
- `src/weave_frontend/merge_policy.py`: revisioned first-parent policy registry.
- `src/weave_frontend/merge_preflight.py`: policy-aware one-call review composition.
- `src/weave_frontend/mcp_preflight.py`: production preflight MCP registration.
- `src/weave_frontend/mcp_policy.py`: final policy-enforced merge registration.
- `src/weave_frontend/mcp_revision_reads.py`: final historical read registration.
- `src/weave_frontend/mcp_build_discovery.py`: verified build-list registration.
- `src/weave_frontend/grammar_help.py`: guidance derived from compiler examples.
- `src/weave_frontend/weavec.py`: authoritative frontend validation adapter.
- `src/weave_frontend/compiler_*.py`: native compiler and artifact boundary.
- `src/weave_frontend/mcp_server.py`: base MCP tools.
- `src/weave_frontend/mcp_build.py`: production MCP entry point and extensions.
- `docs/architecture.md`: broad design and roadmap.
- `docs/mcp.md`: MCP workflow and public tool contract.
- `docs/single-node-concurrency.md`: race-safe structural write contract.
- `docs/edit-transactions.md`: bounded batch request and publication contract.
- `docs/revision-reads.md`: historical rendering and search response contract.
- `docs/build-discovery.md`: verified stored-build recovery and pagination.
- `docs/merge-policy.md`: revisioned target-authoritative admission rules.
- `docs/merge-preflight.md`: one-call review evidence and safe replay.
- `docs/merge-preview.md`: preview identity and atomic merge publication.
- `docs/merge-impact.md`: affected targets and uncovered candidate documents.
- `docs/merge-validation.md`: one-target exact-candidate compiler gate.
- `docs/merge-validation-set.md`: complete affected-target compiler gate.
- `tests/`: executable specifications and real-MCP qualifications.

## Change protocol

Before changing behavior:

1. Read `docs/architecture.md`, `docs/mcp.md`, and affected tests.
2. State the invariant being changed or preserved.
3. Add or update tests with the behavior change.
4. Keep database migrations explicit and backwards-aware.
5. Run:

```bash
python -m compileall -q src tests
ruff check .
pytest
```

## Merge expectations

A passing structural merge is not enough. Resolve and review the target policy,
then use one preflight to inspect the exact incoming impact, source-policy
difference, uncovered documents, and complete affected-target compiler result.
Publish through its returned arguments only when ready and policy-compliant.
After publication, preserve unique node IDs and run any native build or execution
checks required by the task.
