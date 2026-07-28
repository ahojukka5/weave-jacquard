# Typed runtime configuration and service ownership

Jacquard's production MCP application captures supported process configuration once
and owns its core shared services through an explicit runtime container. This makes
startup configuration, service identity, and shutdown behavior stable for the life
of one server process.

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
server. Operators must restart the process to apply configuration changes. This
prevents different lazily created services from observing different generations of
environment state.

The application manifest binds the variable names only. `runtime_identity` reads the
same startup snapshot and publishes domain-separated opaque value IDs without
revealing paths or values.

## Runtime-owned services

`RuntimeServices` currently owns the two roots of the production service graph:

- the race-safe `SExpressionWorkspace` and its SQLite connection;
- the quota-capable committed-build `CompilerBridge`.

Both are created lazily under one reentrant lock and returned by identity on every
subsequent request. The compiler bridge is constructed directly as the quota-aware
production class; normal production startup no longer mutates a cached plain bridge
into another class.

The first declared MCP capability installs runtime-backed `workspace()` and
`compiler_bridge()` factories before dependent capability modules are loaded. Their
public tool names and schemas are unchanged. Existing module factories then compose
build, test, candidate, backup, quota, attestation, and identity services around
those runtime-owned roots.

Artifact roots, sandbox selection, backup location, and quota policy are taken from
the same immutable configuration snapshot when those services are composed.

## Lifecycle

The process runtime has one deterministic lifecycle:

```text
capture RuntimeConfig
→ create RuntimeServices
→ lazily open workspace
→ lazily create compiler bridge
→ compose dependent services
→ serve MCP requests
→ close workspace once at process shutdown
```

`close_runtime_services()` is idempotent. Closing a container clears its owned
references, closes the workspace exactly once, and rejects later access through that
container. Installing a replacement container closes the previous one before the
replacement is used. Replacement and reset hooks exist for qualification and
embedding; they are not live reconfiguration APIs for a running MCP server.

Historical `cache_clear()` and `cache_info()` calls on the production workspace and
compiler factories remain as narrow compatibility adapters for the existing test
suite and incremental migration. Clearing the workspace factory closes the complete
runtime. Clearing only the compiler factory preserves the workspace and recreates a
bridge against that same workspace.

## Production boundary

The guarantee applies to the application assembled through `JacquardApp.compose()`.
Standalone service classes and `weave-build` remain explicit embedding and CLI
interfaces. They may read their own constructor arguments or legacy environment
fallbacks and are not silently attached to the MCP process runtime.

The remaining module-level service caches are dependent graph nodes rather than
owners of database or compiler roots. Future slices can move them into typed
container fields without changing public MCP contracts. The immediate invariant is
that every production service graph begins from one immutable configuration, one
workspace, and one quota-capable compiler bridge.
