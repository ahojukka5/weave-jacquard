# Typed runtime configuration and service ownership

Jacquard composes each MCP application from one immutable `RuntimeConfig`, one
`RuntimeServices` container, and one application-local FastMCP server. The
`ApplicationContext` retained by `JacquardApp` is the ownership boundary: it selects
the exact runtime used during capability installation and public tool execution.

Production capability modules declare tools and runtime-backed service factories.
They do not select a process runtime, scan `sys.modules`, or mutate previously
imported modules. Context-owned installers perform the small amount of ordered
composition work that must occur for an exact application.

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

Changing `os.environ` after the snapshot exists does not reconfigure that runtime.
Operators create a new application runtime or restart the process to apply supported
configuration changes. Lazily created services therefore cannot observe different
generations of startup state.

Standalone constructors and command-line embedding boundaries may still accept
explicit arguments or their documented local fallbacks. They are not production MCP
service composition and are not silently attached to an application runtime.

## Application-owned runtime container

`RuntimeServices` owns or deterministically supplies every production service. Its
roots are:

- the race-safe `SExpressionWorkspace` and SQLite connection;
- the quota-capable committed-build `CompilerBridge`;
- the immutable `RuntimeConfig` used by every configured dependent.

The `runtime_service()` decorator exposes stable no-argument proxy functions while
placing object identity, dependency tracking, invalidation, and shutdown in the
selected `RuntimeServices` container. The historical `cache_clear()` and
`cache_info()` attributes remain narrow compatibility adapters; they are not the
application lifecycle API.

The complete graph includes:

- edit batches, branch activity, revision inspection, diffs, and pinned reads;
- stable-ID revert composition and verified database backups;
- build targets, validation, inspection, and verified discovery;
- merge preview, impact, validation, policy, preflight, and resume snapshots;
- committed-revision test definitions, execution, batches, and impact planning;
- task contracts, task-scoped batches, checkpoints, timelines, and project status;
- virtual-candidate builds, diagnostics, tests, and tested-merge attestations;
- artifact accounting, quota attachment, and retained revision evidence;
- project merge queues, impact queues, merge-train previews, and preflight batches;
- production runtime identity.

Factories are created lazily under one reentrant lock. Nested factory calls record
edges automatically, and declared dependencies describe the graph before first use.
Repeated calls in one runtime return the same object identity. Two runtimes may
materialize the same service names independently with different databases and
artifact roots.

## Explicit capability installation

`install_public_capabilities()` validates the ordered `PUBLIC_CAPABILITIES` graph and
runs inside `bind_application_runtime(context.runtime)`. For each capability it:

1. imports the declaration module;
2. invokes the exact context-owned production installer when one is registered;
3. otherwise invokes a custom installer only when it accepts exactly one
   `ApplicationContext`;
4. clones that capability's declared tool models onto `context.server`;
5. installs final application-local guidance;
6. finalizes and binds the exact application tool set.

The production installer table is immutable and keyed by both capability name and
module name. Installers verify that the selected runtime is the runtime retained by
the context. Their cache invalidation and quota attachment affect only that runtime.
Repeated composition is deterministic and preserves public tool names and schemas.

The canonical decorated server remains a source catalog for tool declarations. It is
not the running application's ownership boundary. Production tools are installed
onto the selected `context.server`, and incomplete explicit assembly fails closed.

## Scoped runtime selection

`bind_application_runtime()` selects one `RuntimeServices` instance for the current
execution context and inherited child tasks, then restores the previous selection.
Application-local tool wrappers perform that binding for complete synchronous or
asynchronous invocations.

This allows two complete applications in one process to execute against different
SQLite databases and retained-artifact roots without changing the process-default
runtime or contaminating each other's lazy-service caches. Nested calls in the same
runtime remain reentrant.

A process-default runtime remains available for the exported public application and
legacy embedding adapters. Tests and additional applications should pass and bind an
explicit `RuntimeServices` instance instead of rewriting private process globals or
clearing unrelated module caches.

## Dependency-aware invalidation and shutdown

One application runtime follows this lifecycle:

```text
capture RuntimeConfig
→ create RuntimeServices
→ compose ApplicationContext
→ install capabilities and application-local tools
→ lazily materialize named services
→ bind the runtime for each tool invocation
→ close realized services in reverse dependency order
```

The container derives close order from service dependencies, not merely creation
order. Dependents close before resources they use, duplicate object identities close
once, and repeated `close()` calls are harmless. A closed runtime rejects later
service access.

Clearing one named service also clears every realized dependent. Publisher
replacement therefore invalidates artifact accounting, quota attachment, and
revision-evidence services that captured it. Clearing the compiler bridge invalidates
all bridge-dependent build and test services. Clearing the workspace invalidates its
entire transitive application graph.

Application owners close `context.runtime`; they do not enumerate module caches.
Closing one application runtime does not close or reset another runtime in the same
process.

## Stable production proxies

`mcp_server.workspace`, `mcp_build.workspace`, and
`mcp_concurrent_nodes.workspace` reference the same stable runtime-backed proxy.
The committed compiler bridge and all migrated service factories follow the same
model.

Production capability installation does not:

- scan or mutate `sys.modules`;
- replace imported service bindings;
- reread supported startup variables;
- clear a hand-maintained cross-module cache list;
- transfer a shared registry into the running server.

All FastMCP private-registry compatibility is isolated in `fastmcp_registry.py` and
the focused application tool-registration adapters. Other production composition
modules consume validated adapter operations instead of reading SDK-private fields.

## Service-graph identity

`RuntimeServices.service_manifest()` returns
`weave-jacquard-runtime-service-graph-v1` evidence containing:

- every known service name;
- its factory origin;
- deterministic dependency names;
- the complete service count;
- a content-derived `service_graph_id`.

Lazy initialization state is optional diagnostic evidence and is excluded from the
graph hash. The public `runtime_identity` report includes the state-free service
graph and recomputes `runtime_id` from the exact application, tool, configuration,
compiler, database, sandbox, and service-composition evidence.

Filesystem paths, configured values, and incidental first-use order are not exposed
in the service graph. Configured values appear only as domain-separated opaque IDs.

## Contributor invariants

- Add production services through `RuntimeServices` and declare dependencies.
- Read supported MCP configuration only through `RuntimeConfig`.
- Install production capabilities through an exact `ApplicationContext`.
- Register running tools on `context.server`, never by mutating a shared live server.
- Bind the retained runtime for every application-local tool invocation.
- Close only runtimes and resources owned by the current application or test.
- Keep standalone constructors explicit and separate from MCP composition.
- Treat service-graph, tool-contract, and application identity changes as reviewed
  compatibility changes.
