# Typed runtime configuration and service ownership

Jacquard's production MCP application captures supported process configuration once
and owns shared services through an explicit runtime container. Startup
configuration, service identity, dependency ownership, and shutdown behavior remain
stable for the life of one server process.

## Immutable configuration snapshot

`RuntimeConfig` reads the supported environment contract once:

```text
WEAVEC_BIN
WEAVEC_SOURCE_ROOT
WEAVE_ARTIFACT_MAX_BYTES
WEAVE_BUILD_ROOT
WEAVE_BWRAP
WEAVE_DATABASE_BACKUP_ROOT
WEAVE_DB_PATH
WEAVE_MERGE_ATTESTATION_ROOT
WEAVE_MERGE_BUILD_ROOT
WEAVE_MERGE_TEST_RUN_ROOT
WEAVE_TEST_BATCH_ROOT
WEAVE_TEST_RUN_ROOT
```

Empty values are treated as unset. The aggregate artifact quota is parsed and
validated during snapshot creation. Paths and executable selections are stored as
typed values, while an immutable mapping of explicitly configured string values is
retained for redacted runtime identity.

Changing `os.environ` after the snapshot exists does not reconfigure a running
server. Operators restart the process to apply configuration changes. This prevents
lazily created services from observing different generations of environment state.

The application manifest binds variable names only. `runtime_identity` reads the
same startup snapshot and publishes domain-separated opaque value IDs without
revealing paths or values.

## Runtime-owned service registry

`RuntimeServices` owns the roots of the production graph:

- the race-safe `SExpressionWorkspace` and SQLite connection;
- the quota-capable committed-build `CompilerBridge`.

It also supplies a named lazy-service registry. The `runtime_service()` decorator
moves a no-argument production factory into that registry while retaining the
historical callable, `cache_clear()`, and `cache_info()` surface expected by existing
qualification code.

The migrated foundational build, merge, read, and recovery graph includes:

```text
workspace
├── edit_batches
├── branch_activity
├── revision_inspection
├── revision_diffs
├── revision_reads
├── database_backups
├── merge_previews
│   └── reverts
└── build_targets
    ├── build_target_validator
    ├── merge_impacts
    └── merge_validations
        └── merge_validation_sets

compiler_bridge
├── build_inspection
└── build_discovery
```

The committed-revision behavioral-test graph is also runtime-owned:

```text
workspace
└── test_targets
    ├── test_target_pages
    ├── test_runs
    │   └── test_batches
    └── test_impact_plans
```

The task and agent-continuity graph is runtime-owned as well:

```text
workspace
├── task_contracts
│   └── task_scoped_batches
└── agent_checkpoints
    ├── checkpoint_timelines
    └── project_agent_statuses
```

`test_runs` additionally depends on `workspace`, `build_targets`, and
`compiler_bridge`. `test_batches` additionally declares its direct workspace
dependency, and `test_impact_plans` also depends on `workspace` and `build_targets`.
`task_scoped_batches` additionally depends on `edit_batches`. `reverts` similarly
declares its direct workspace dependency.

Factories are created lazily under one reentrant lock. Nested factory calls record
dependency edges automatically, while declared dependencies document edges before a
service is materialized. Repeated calls return the same object identity.

## Stable production proxies

`mcp_server.workspace` is now a stable runtime-backed function from its first import.
`mcp_build.workspace` and `mcp_concurrent_nodes.workspace` reference that same
function object. The committed compiler factory is similarly a stable proxy to the
container-owned compiler bridge.

Production capability installation no longer scans or mutates `sys.modules`, swaps
previously imported workspace bindings, or clears an ad hoc list of build caches.
The first capability only ensures that the immutable process runtime exists. Tool
names and schemas are unchanged.

The standalone service classes and `weave-build` CLI remain explicit embedding
boundaries. They may use constructor arguments or documented legacy fallbacks; they
are not silently attached to the MCP process runtime.

## Dependency-aware lifecycle

The process runtime follows this lifecycle:

```text
capture RuntimeConfig
→ create RuntimeServices
→ lazily create named services
→ record service dependencies
→ serve MCP requests
→ close realized services in reverse dependency order
```

The container derives close order from service dependencies, not only from creation
order. Dependents therefore close before the resources they use even when a declared
dependency was materialized later. Duplicate object identities are closed only once.
Closing is idempotent, clears owned references, and rejects later access through the
closed container.

Clearing one named dependency also clears every realized dependent recorded in the
graph. Clearing the compiler bridge therefore cannot leave runtime-owned build
inspection, build-discovery, or behavioral-test execution services holding the
discarded bridge. Clearing the workspace also invalidates revision reads, revert
composition, database backups, behavioral-test services, task services, checkpoint
services, project agent-status pages, and their transitive runtime-owned
dependencies. Replacing the process container closes the previous container before
the replacement is used.

`workspace.cache_clear()` remains the compatibility operation that closes and resets
the entire process runtime. `compiler_bridge.cache_clear()` clears the bridge and
its runtime-owned dependents while preserving the workspace.

## Service-graph identity

`RuntimeServices.service_manifest()` returns
`weave-jacquard-runtime-service-graph-v1` evidence containing:

- each known service name;
- its factory origin;
- deterministic dependency names;
- the complete service count;
- a content-derived `service_graph_id`.

Decorator declarations are registered when their modules are composed. The graph ID
therefore describes service composition and does not change merely because another
lazy service is used for the first time. Optional state evidence reports the current
`initialized_services` and `initialized_service_count` separately and is excluded
from the graph hash.

The production `runtime_identity` report includes the state-free graph manifest and
recomputes its `runtime_id` over that stable composition evidence. Filesystem paths,
configured values, and incidental lazy-initialization order are not included in the
service graph.

The graph describes runtime-owned services known to the current container. It does
not claim that the remaining legacy capability factories have already migrated.

## Remaining issue #106 work

The typed graph now owns the task-contract, task-scoped edit, checkpoint, checkpoint
timeline, and project agent-status services in addition to the foundational and
committed-revision behavioral-test graphs.

Resume snapshots, merge-policy and preflight composition, artifact services,
project merge orchestration, selected-merge workflows, virtual-candidate tests,
attestations, and retained-evidence factories still contain module-local lazy
caches. Follow-up work will move those factories onto the same registry, inject an
explicit runtime/application context into capability installation, isolate FastMCP
registry compatibility, and prove that two complete applications can coexist in one
process without global cross-contamination.
