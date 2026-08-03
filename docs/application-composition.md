# Explicit application composition

## Purpose

The production Jacquard MCP surface is composed as one explicit `JacquardApp`.
Each application retains one `ApplicationContext` containing the exact FastMCP
server and `RuntimeServices` container selected for that application.

The application object is the final boundary for:

- the validated capability dependency graph;
- immutable typed runtime configuration;
- deterministic production-service ownership;
- explicit and idempotent capability installation;
- application-local public MCP tool models;
- request-time runtime binding;
- exact capability, tool, application, service-graph, and runtime identities.

The public entry point exports:

```text
PUBLIC_APP
PUBLIC_CAPABILITY_MANIFEST
PUBLIC_TOOL_MANIFEST
PUBLIC_APPLICATION_MANIFEST
```

## Final ownership model

`JacquardApp.compose(server, runtime=...)` creates an `ApplicationContext` from the
selected server and runtime, installs the declared capability graph, validates the
final application-local tool registry, and captures immutable manifests.

The ownership relationships are:

```text
JacquardApp
├── server
└── ApplicationContext
    ├── server
    └── RuntimeServices
        ├── RuntimeConfig
        ├── workspace and SQLite connection
        ├── compiler bridge
        └── complete lazy production service graph
```

The canonical decorated FastMCP server is a declaration catalog used to discover
source tool models. It is not the running application's server. Foundational,
`mcp_build`, capability-owned, and guidance tool models are installed directly on
the selected `context.server`, then transactionally reduced to the canonical public
set.

Production capability modules are declaration-only unless they expose an explicitly
supported custom installer accepting exactly one `ApplicationContext`. Runtime
selection, service invalidation, metadata restoration, artifact quota attachment,
and runtime-identity recomposition belong to the context-owned installer table.

## Composition sequence

Canonical production startup follows one explicit sequence:

```text
create application-local FastMCP server
→ capture or supply immutable RuntimeConfig
→ create or supply RuntimeServices
→ create ApplicationContext
→ bind the context runtime
→ validate the ordered capability graph
→ install foundational and mcp_build tool models
→ run context-owned production installers
→ install each capability's tool models
→ install final application-local guidance
→ retain and bind the canonical application tool set
→ validate tool contracts and required names
→ capture tool and application manifests
→ serve requests
```

Composition fails before serving requests when the capability graph, runtime,
configuration, registry shape, tool names, schemas, metadata, or required public
surface is invalid.

Invalid `WEAVE_ARTIFACT_MAX_BYTES` fails during configuration capture, before the
server advertises a contract it cannot enforce.

## Capability graph and installers

`PUBLIC_CAPABILITIES` declares dependency-before-dependent ordering. Validation
rejects empty or duplicate names and dependencies that have not appeared earlier.
The resulting manifest is stable JSON-ready evidence.

`install_public_capabilities()` executes only with an exact `ApplicationContext`.
Inside a scoped runtime binding it:

- imports each declared capability module;
- dispatches exact production installers by capability and module name;
- accepts custom installers only when their signature contains one context
  parameter;
- clones capability-owned tool models onto the selected server;
- installs final guidance;
- finalizes the canonical tool set and runtime-bound callables.

The production installer mapping is immutable. Every installer verifies that
`runtime_services()` resolves to `context.runtime`. Service clearing and quota
attachment therefore affect only the application being composed.

Repeated installation on the same valid context is deterministic. Production
installers do not scan modules, mutate imported bindings, or use zero-argument
ambient-runtime hooks.

## Application-local tool registration

Tool declarations may originate from decorated source modules, but the running
application receives its own tool objects. Registration proceeds by ownership:

- foundational models are cloned by the core registration phase;
- `mcp_build` models are cloned by their defining module phase;
- each declared capability installs only its own models;
- final guidance replaces the local help model;
- finalization retains the exact canonical names and rejects incomplete assembly.

The application does not synchronize or transfer an historical shared registry as a
fallback. Custom application servers retain only the models explicitly installed for
their requested capability set.

Application-local wrappers preserve generated argument models, input and output
schemas, descriptions, annotations, icons, metadata, and canonical callable lineage.
They bind `context.runtime` for the complete synchronous or asynchronous invocation
and restore the previous runtime afterward.

## Two applications in one process

Callers may compose two `JacquardApp` instances with distinct `RuntimeServices`,
database paths, build roots, test roots, backup roots, and artifact roots. The two
applications may initialize and execute public tools concurrently.

Runtime selection is context-local. One application's tool call cannot select the
other application's workspace or service cache, and closing one runtime does not
close or reset the other. The process-default runtime remains unchanged by explicit
application calls.

Tests create and close exact runtimes rather than rewriting private process globals
or clearing broad lists of module caches.

## Typed runtime configuration

`RuntimeConfig` captures all supported production environment values once. Empty
values are treated as unset, paths and executables become typed values, and the
aggregate artifact quota is validated immediately.

A running application does not observe later environment mutations. The application
manifest exposes only supported variable names. Runtime identity receives an
immutable mapping of explicitly configured values and emits opaque matching IDs
rather than raw values or paths.

See [typed runtime configuration and service ownership](runtime-container.md).

## Runtime-owned services

`RuntimeServices` owns the workspace, SQLite connection, compiler bridge, and the
complete named lazy production graph. That graph covers revision, build, merge,
test, task, checkpoint, candidate qualification, attestation, artifact, project
orchestration, evidence, backup, and runtime-identity services.

Factories retain stable callable proxies while the selected container owns object
identity, dependency evidence, invalidation, and shutdown. Clearing a dependency
invalidates every realized dependent that captured it.

`weave-jacquard-runtime-service-graph-v1` records every service name, factory origin,
and deterministic dependency. Its `service_graph_id` excludes lazy initialization
state. Optional diagnostics report initialized services separately.

## Tool manifest v2

`weave-jacquard-tool-manifest-v2` binds the caller-visible contract for every
registered application-local tool:

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

Each canonical entry has a `tool_contract_id`. The lexically ordered complete set has
a `tool_manifest_id`, tool count, and parallel `tool_names` list. Registry insertion
order does not affect identity.

Changing a parameter schema, output schema, description, annotation, icon, or
metadata changes the relevant contract and manifest identities. Unsupported values,
non-finite numbers, non-string mapping keys, missing mapping input schemas, and
invalid output schemas are startup errors.

The manifest is API evidence. It does not hash implementation bytes, mutable service
state, database contents, or artifact paths.

## Application manifest v2

`weave-jacquard-application-v2` binds:

- the ordered capability graph;
- `tool_manifest_id` and tool count;
- every supported runtime configuration-variable name in lexical order.

Its `application_id` changes when the public tool contract, capability graph, or
configuration surface changes. It is not a security token or qualification result.
Syntax, unit, real-MCP, packaged-compiler, sandbox, and native execution evidence
remain separate requirements.

## Runtime identity v1

The public `runtime_identity` tool binds:

- application, tool-manifest, capability, and service-graph identities;
- Jacquard, Python, and MCP versions;
- Python executable identity;
- database schema and connection policy;
- compiler binary and bounded version evidence;
- sandbox policy and runtime identities;
- configured variable names and opaque value IDs.

Runtime identity reads the exact runtime selected for its application-local tool
call. It includes the state-free service graph and is not affected by incidental
lazy first-use order.

Runtime identity is audit-correlation evidence, not a qualification result. See
[runtime identity](runtime-identity.md) and [qualification](qualification.md).

## Lifecycle

`RuntimeServices.close()` is idempotent. It closes realized services once in reverse
dependency order, clears owned references, and rejects later access. Application
owners close the runtime retained by their context.

Compatibility `cache_clear()` and `cache_info()` adapters remain for standalone
embedding and focused qualification. They are not live reconfiguration APIs.
Operators create a new runtime or restart the production process to apply supported
configuration changes.

## MCP SDK compatibility boundary

All FastMCP registry and registered-tool metadata access is isolated in
`fastmcp_registry.py` and focused application registration adapters. These adapters:

- capture supported mapping-backed registry shapes;
- validate registry keys and declared names;
- clone selected tool models;
- replace, retain, and roll back application-local registrations atomically;
- extract the protocol-visible tool contract fields.

No other production composition module directly reads SDK-private registry fields.
A future SDK public synchronous tool-list API should be adopted inside this boundary
without creating a second application assembly path or changing equivalent public
identities.

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
Paths and values are absent from composition metadata.

## Contributor rules

- Add public capabilities through `PUBLIC_CAPABILITIES` in dependency order.
- Compose running applications through `JacquardApp.compose()`.
- Pass an explicit runtime when creating additional applications or tests.
- Read production configuration through `RuntimeConfig`.
- Add production lazy services through `RuntimeServices`.
- Put production installation side effects in context-owned installers.
- Install running tool models on `context.server` through the registry adapters.
- Bind the retained runtime for every application-local public invocation.
- Treat tool-contract, application-manifest, and service-graph changes as public
  compatibility changes requiring review and qualification.
- Do not expose configured values or server-local paths in public manifests.
- Preserve `weavec` as the authoritative compiler and language implementation.
