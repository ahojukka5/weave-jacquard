# Explicit application composition

## Purpose

The production Jacquard MCP server is exposed as one explicit `JacquardApp` rather
than only as a process-global `FastMCP` object assembled indirectly by imports.
The application object is the final startup boundary for:

- the validated capability dependency graph;
- final capability installation, including idempotent cached-module installers;
- the exact registered public MCP tool contracts;
- content-derived capability, tool-contract, tool-manifest, and application
  identities;
- the documented runtime configuration-variable contract.

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
tool identity and the complete manifest identity even when the tool name is
unchanged. Registry insertion order does not affect either identity.

Jacquard captures one registry snapshot for each extraction. Registry keys must
already be non-empty strings; they are never coerced with `str()`. This prevents a
non-string key from being hashed under one name and looked up under another.
Contracts passed to the manifest builder may contain only the protocol fields
listed above. Unknown fields are rejected rather than silently excluded from the
identity.

The normalizer accepts JSON primitives, finite numbers, string-keyed mappings,
sequences, dataclasses, enums, and Pydantic values through
`model_dump(mode="json")`. Unsupported values, failed model serialization,
non-finite numbers, non-string keys, missing input schemas, and non-mapping output
schemas are startup errors rather than silently omitted contract data.

The manifest is API evidence. It does not hash the Python implementation, service
state, compiler binary, database contents, or runtime artifact paths.

## Application manifest v2

`weave-jacquard-application-v2` binds:

- the ordered capability graph;
- `tool_manifest_id` and tool count;
- every supported runtime configuration-variable name in lexical order.

Its `application_id` therefore changes when the public tool contract, capability
graph, or configuration surface changes. It is not a security token, release
version, or proof that every tool behaves correctly. Syntax, unit, real-MCP,
packaged-compiler, sandbox, and native execution qualification remain required.

## Runtime identity v1

The application manifest intentionally excludes live component values. The public
`runtime_identity` tool adds a separate content-derived live report that binds:

- `application_id`, `tool_manifest_id`, tool count, and capability count;
- Jacquard, Python, and MCP versions;
- Python executable hash;
- database schema and connection policy;
- final compiler binary hash and bounded version evidence;
- sandbox policy and Bubblewrap and `prlimit` binary hashes;
- which public configuration variables are set, without revealing their values.

The runtime identity tool is itself part of the tool manifest. Its function reads
the completed public application manifest lazily only when called. There is no
hash cycle: the application ID binds the tool contract, while the runtime ID binds
the already completed application ID and current component evidence.

Runtime identity is diagnostic and audit-correlation evidence. It is not a
qualification result. See [runtime identity](runtime-identity.md) and
[qualification](qualification.md).

## Startup invariant

Production startup follows one explicit sequence:

```text
base decorated server
→ ordered capability installation
→ final guidance installation
→ one registered tool-registry snapshot
→ schema and required-tool validation
→ content-derived application manifest snapshot
→ stdio transport
```

Composition fails before serving requests when:

- the FastMCP tool registry cannot be inspected through a supported mapping shape;
- no tools were registered;
- registry keys are not non-empty strings;
- tool names disagree with registered metadata;
- a required public tool is missing;
- a tool lacks a mapping input schema;
- an output schema is non-null and not a mapping;
- a supplied contract contains unknown fields;
- contract metadata cannot be represented canonically as JSON;
- configuration-variable names are empty or duplicated;
- the capability graph is invalid.

## Current migration boundary

Most existing MCP modules still register decorated tools on the shared server at
module import time. The application object deliberately does not hide that fact.
It provides the stable outer composition boundary needed to migrate individual
capabilities incrementally toward pure installers or factories without changing
public tool names or schemas.

The v1 MCP Python SDK exposes tool metadata through the FastMCP tool-manager
registry. Jacquard currently supports its mapping-backed `_tools` shape and the
mapping-backed fake-server shape used by composition tests. This remains an SDK
compatibility boundary even though the extracted fields correspond directly to
the protocol `tools/list` contract.

During migration:

1. Every capability remains declared in `PUBLIC_CAPABILITIES` with explicit
   dependency-before-dependent ordering.
2. Cached modules that must restore service composition expose an idempotent
   `install_capability()` hook.
3. Final guidance is installed once after all declared capabilities.
4. `JacquardApp.compose()` validates and hashes the resulting tool contracts.
5. Tests compare the exported manifests with the actual production entry point.

A later capability-factory refactor should replace module side effects behind this
same application boundary. A later MCP SDK should be adopted through a supported
public tool-list API when one is available synchronously at startup. Neither
migration may introduce a second public server assembly path.

## Configuration contract

The application manifest names, but does not reveal values for, these supported
runtime variables:

- `WEAVEC_BIN`;
- `WEAVEC_SOURCE_ROOT`;
- `WEAVE_BUILD_ROOT`;
- `WEAVE_BWRAP`;
- `WEAVE_DB_PATH`;
- `WEAVE_MERGE_ATTESTATION_ROOT`;
- `WEAVE_MERGE_BUILD_ROOT`;
- `WEAVE_MERGE_TEST_RUN_ROOT`;
- `WEAVE_TEST_BATCH_ROOT`;
- `WEAVE_TEST_RUN_ROOT`.

The names are validated as a unique lexical set before the application identity is
computed. Paths and secrets are intentionally absent from public composition
metadata. Runtime identity reports only the subset of variable names whose values
are non-empty. Runtime artifact manifests continue to bind exact compiler,
executable, sandbox, and content hashes where those identities matter.

## Contributor rules

- Add a new public capability through the declared capability graph.
- Never create another production entry point that bypasses `JacquardApp.compose()`.
- Treat tool-contract and manifest changes as public API changes requiring review
  and real-MCP qualification.
- Keep schemas and metadata JSON-canonical and deterministic.
- Do not add environment values or server-local paths to public application
  manifests or runtime identity reports.
- Preserve `weavec` as the authoritative compiler and language implementation.
