# Explicit application composition

## Purpose

The production Jacquard MCP server is exposed as one explicit `JacquardApp` rather
than only as a process-global `FastMCP` object assembled indirectly by imports. The
application object is the final startup boundary for:

- the validated capability dependency graph;
- typed immutable runtime configuration;
- deterministic ownership of runtime services;
- final idempotent capability installation;
- exact registered public MCP tool contracts;
- content-derived capability, tool-contract, tool-manifest, application, service
  graph, and runtime identities.

The public entry point exports:

```text
PUBLIC_APP
PUBLIC_CAPABILITY_MANIFEST
PUBLIC_TOOL_MANIFEST
PUBLIC_APPLICATION_MANIFEST
```

## Tool manifest v2

`weave-jacquard-tool-manifest-v2` binds the complete caller-visible contract for
every registered tool:

```text
name
title
description
input_schema
output_schema
annotations
icons
meta
```

Each canonical entry has a `tool_contract_id`. The complete lexically ordered
contract list has a `tool_manifest_id` and a parallel `tool_names` convenience
list.

Changing a parameter type, required argument, default encoded in JSON Schema,
output schema, description, annotation, icon, or metadata changes the individual
tool identity and complete manifest identity even when the tool name is unchanged.
Registry insertion order does not affect either identity.

Jacquard captures one registry snapshot for each extraction. Registry keys must be
non-empty strings and are never coerced with `str()`. Contracts may contain only the
supported protocol fields. Unknown fields are rejected rather than silently
excluded from identity.

The normalizer accepts JSON primitives, finite numbers, string-keyed mappings,
sequences, dataclasses, enums, and Pydantic values through
`model_dump(mode="json")`. Unsupported values, failed model serialization,
non-finite numbers, non-string keys, missing input schemas, and non-mapping output
schemas are startup errors.

The manifest is API evidence. It does not hash Python implementation bytes, mutable
service state, database contents, or artifact paths.

## Application manifest v2

`weave-jacquard-application-v2` binds:

- the ordered capability graph;
- `tool_manifest_id` and tool count;
- every supported runtime configuration-variable name in lexical order.

Its `application_id` changes when the public tool contract, capability graph, or
configuration surface changes. It is not a security token, release version, or
proof that every tool behaves correctly. Syntax, unit, real-MCP,
packaged-compiler, sandbox, and native execution qualification remain required.

## Typed runtime configuration

Before a production service is first used, `RuntimeConfig` captures all supported
environment values into one frozen typed snapshot. Empty values are treated as
unset and the aggregate artifact quota is parsed immediately. A running process
does not observe later environment mutations.

The snapshot includes database, compiler, sandbox, artifact-root, backup-root, and
quota configuration. The application manifest exposes only supported variable
names. Runtime identity receives an immutable mapping of explicitly configured
values and emits opaque matching IDs rather than raw values or paths.

See [typed runtime configuration and service ownership](runtime-container.md).

## Runtime-owned services

`RuntimeServices` owns the production roots:

- one race-safe `SExpressionWorkspace` and SQLite connection;
- one quota-capable committed-build `CompilerBridge`.

It also provides a named lazy-service registry. Production factories migrated with
`runtime_service()` retain their existing callable and cache-adapter surface while
the container owns identity, dependency evidence, invalidation, and shutdown.

The runtime-owned graph now includes:

- edit batches and branch activity;
- revision inspection, diff, pinned reads, and stable-ID revert composition;
- merge preview, impact, validation, validation sets, policy, and preflight;
- build targets, target validation, build inspection, and verified build discovery;
- verified online database backups;
- committed-revision behavioral-test definitions and bounded pages;
- strict behavioral-test execution, explicit batches, and structural impact plans;
- task contracts and task-scoped structural batches;
- agent checkpoints, checkpoint timelines, and project agent-status pages;
- bounded revision-pinned resume snapshots;
- virtual-candidate builds, diagnostics, test-impact plans, and strict test batches;
- tested-merge state-identity attestations;
- aggregate retained-artifact accounting and quota attachment;
- project merge queues and non-compiling project merge-impact queues;
- selected merge-train previews and selected compiler-backed preflight batches;
- bounded retained revision-evidence discovery;
- compiler bridge and production runtime identity.

The behavioral-test graph records exact dependencies on the workspace, build-target
registry, test-definition registry, compiler bridge, and immutable runtime
configuration. The task and agent-continuity graph similarly binds task-scoped edits
to task contracts and edit batches, and binds timelines and project status to the
checkpoint registry. Merge preflight binds impact, affected-target validation, and
target-branch policy. Resume snapshots bind workspace, build targets, policy,
checkpoints, behavioral tests, and task contracts. Virtual-candidate qualification
binds merge previews, build targets, test definitions, the compiler bridge, and the
immutable artifact-root configuration. Tested-merge attestations bind the workspace
to exact candidate test qualifications. Artifact accounting binds every retained
publisher root, while quota attachment binds that accounting, the workspace, and all
publishers that receive the shared guard. Project merge queues bind merge previews
to agent-status catalogs. Impact queues add target coverage and policy, while
selected train and preflight workflows bind their exact catalog to that shared queue.
Revision-evidence discovery binds the workspace and retained publisher verifiers so
publisher replacement invalidates the captured evidence graph. Clearing a root
therefore invalidates every realized dependent that captured it.

`mcp_server.workspace`, `mcp_build.workspace`, and
`mcp_concurrent_nodes.workspace` are the same stable runtime-backed function from
their first import. The compiler bridge has the same stable-proxy property.
Capability installation no longer scans `sys.modules`, replaces bindings in
previously imported modules, or clears a hand-maintained list of foundational
service caches.

The compiler bridge is constructed directly as the production quota-aware class.
The historical in-place bridge upgrade remains only as a narrow standalone
compatibility path; normal public startup does not rely on class mutation.

## Runtime service graph

`weave-jacquard-runtime-service-graph-v1` records the service name, factory origin,
and explicit dependencies for every service known to the typed registry. Its
`service_graph_id` excludes lazy initialization state, so first use of an already
composed service does not redefine runtime identity.

Optional container diagnostics may report initialized service names separately.
The public `runtime_identity` report binds only the stable composition graph.

Every production service factory is represented in the typed service graph. Issue
#106 remains open for the application and registration boundaries rather than for
untracked production service ownership.

## Runtime identity v1

The application manifest intentionally excludes live component values. The public
`runtime_identity` tool adds a separate content-derived report binding:

- `application_id`, `tool_manifest_id`, tool count, and capability count;
- typed service graph and graph ID;
- Jacquard, Python, and MCP versions;
- Python executable hash;
- database schema and connection policy;
- final compiler binary hash and bounded version evidence;
- sandbox policy and Bubblewrap and `prlimit` binary hashes;
- configured public variable names and domain-separated opaque value IDs.

The runtime identity tool is itself part of the tool manifest. It reads the
completed public application manifest lazily. There is no hash cycle: application
identity binds the tool contract, while runtime identity binds the completed
application ID and current component evidence.

Runtime identity is diagnostic and audit-correlation evidence, not a qualification
result. See [runtime identity](runtime-identity.md) and
[qualification](qualification.md).

## Startup invariant

Production startup follows one explicit sequence:

```text
base decorated server
→ immutable RuntimeConfig snapshot
→ RuntimeServices creation
→ ordered capability installation
→ runtime-owned lazy service declarations
→ artifact-root composition and optional quota attachment
→ final guidance installation
→ one registered tool-registry snapshot
→ schema and required-tool validation
→ content-derived application manifest snapshot
→ stdio transport
```

Invalid `WEAVE_ARTIFACT_MAX_BYTES` fails during configuration snapshot creation,
before the server advertises a contract it cannot enforce.

Composition fails before serving requests when:

- the FastMCP tool registry cannot be inspected through a supported mapping shape;
- no tools were registered;
- registry keys are not non-empty strings;
- tool names disagree with registered metadata;
- a required public tool is missing;
- a tool lacks a mapping input schema;
- an output schema is non-null and not a mapping;
- supplied contract metadata is unsupported or not JSON-canonical;
- configuration-variable names are empty or duplicated;
- the capability graph is invalid;
- typed runtime or aggregate quota configuration is malformed.

## Lifecycle

`RuntimeServices.close()` is idempotent. It closes realized services once in
reverse dependency order, clears owned references, and rejects later access through
the closed container. An explicit replacement closes the previous runtime. Process
shutdown is registered through `atexit`.

Clearing a named dependency invalidates every realized runtime-owned dependent.
Compatibility `cache_clear()` and `cache_info()` adapters remain on migrated
factories for qualification and embedding. Clearing any retained publisher also
invalidates aggregate accounting, quota attachment, and retained revision evidence
where applicable. Clearing project merge queues invalidates their impact and
selected-source workflow dependents. Clearing the workspace resets the whole process
runtime; clearing the compiler bridge preserves the workspace while invalidating
bridge-dependent committed and virtual-candidate build, accounting, quota, and
revision-evidence services.

These hooks are not live reconfiguration APIs. Operators restart the MCP process to
apply environment changes.

## MCP SDK compatibility boundary

Most MCP modules still register decorated tools on the shared server at import time.
The application object does not hide that fact. It provides the stable outer
composition boundary needed to migrate dependent services without changing public
names or schemas.

The MCP Python SDK exposes tool metadata through the FastMCP tool-manager registry.
Jacquard supports its mapping-backed `_tools` shape and the mapping-backed fake
server used by tests. This remains an SDK compatibility boundary even though the
extracted fields correspond to the protocol `tools/list` contract.

A later SDK should be adopted through a supported public tool-list API when one is
available synchronously at startup. The migration must not introduce a second
production server assembly path.

## Configuration contract

The application manifest names, but does not reveal values for:

- `WEAVEC_BIN`;
- `WEAVEC_SOURCE_ROOT`;
- `WEAVE_ARTIFACT_MAX_BYTES`;
- `WEAVE_BUILD_ROOT`;
- `WEAVE_BWRAP`;
- `WEAVE_DATABASE_BACKUP_ROOT`;
- `WEAVE_DB_PATH`;
- `WEAVE_MERGE_ATTESTATION_ROOT`;
- `WEAVE_MERGE_BUILD_ROOT`;
- `WEAVE_MERGE_TEST_RUN_ROOT`;
- `WEAVE_TEST_BATCH_ROOT`;
- `WEAVE_TEST_RUN_ROOT`.

Names are validated as a unique lexical set before application identity is computed.
Paths and values are absent from composition metadata. Artifact manifests continue
to bind exact compiler, executable, sandbox, and content hashes where those
identities matter.

## Remaining issue #106 work

The typed container now deterministically supplies every production service,
including retained revision-evidence discovery. No production service factory uses
independent module-local `lru_cache` ownership.

Follow-up work must inject an explicit runtime/application context into capability
installation, isolate all FastMCP private-registry access in one adapter, remove the
remaining shared-server installation assumptions, and prove that two complete
applications with different databases and artifact roots can coexist in one process
without cross-contamination. Fixture cleanup and final documentation should then
state the completed per-application ownership model.

## Contributor rules

- Add public capabilities through the declared dependency graph.
- Never create a production entry point that bypasses `JacquardApp.compose()`.
- Read production configuration through `RuntimeConfig`, not ad hoc environment
  access in MCP composition modules.
- Add production lazy services through the typed runtime registry.
- Treat tool-contract and manifest changes as public API changes requiring review
  and real-MCP qualification.
- Keep schemas and metadata JSON-canonical and deterministic.
- Do not expose environment values or server-local paths in public manifests.
- Preserve `weavec` as the authoritative compiler and language implementation.
