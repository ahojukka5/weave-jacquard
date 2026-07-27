# Explicit application composition

## Purpose

The production Jacquard MCP server is exposed as one explicit `JacquardApp` rather
than only as a process-global `FastMCP` object assembled indirectly by imports.
The application object is the final startup boundary for:

- the validated capability dependency graph;
- final capability installation, including idempotent cached-module installers;
- the exact registered public tool-name set;
- content-derived capability, tool, and application identities;
- the documented runtime configuration-variable contract.

The public entry point exports:

```text
PUBLIC_APP
PUBLIC_CAPABILITY_MANIFEST
PUBLIC_TOOL_MANIFEST
PUBLIC_APPLICATION_MANIFEST
```

`PUBLIC_TOOL_MANIFEST` is lexically ordered and contains a deterministic
`tool_manifest_id`. `PUBLIC_APPLICATION_MANIFEST` binds that tool identity to the
ordered capability graph and the supported configuration-variable names.

## Startup invariant

Production startup follows one explicit sequence:

```text
base decorated server
→ ordered capability installation
→ final guidance installation
→ registered-tool validation
→ immutable application manifest
→ stdio transport
```

Composition fails before serving requests when:

- the FastMCP tool registry cannot be inspected through a supported mapping shape;
- no tools were registered;
- tool names are empty or duplicate;
- a required public tool is missing;
- the capability graph is invalid.

The application identity is evidence of one exact public composition. It is not a
security token, a release version, or proof that every tool behaves correctly.
Normal syntax, unit, real-MCP, packaged-compiler, and native execution qualification
remain required.

## Current migration boundary

Most existing MCP modules still register decorated tools on the shared server at
module import time. The application object deliberately does not hide that fact.
It provides the stable outer composition boundary needed to migrate individual
capabilities incrementally toward pure installers or factories without changing
public tool names or schemas.

During migration:

1. Every capability remains declared in `PUBLIC_CAPABILITIES` with explicit
   dependency-before-dependent ordering.
2. Cached modules that must restore service composition expose an idempotent
   `install_capability()` hook.
3. Final guidance is installed once after all declared capabilities.
4. `JacquardApp.compose()` validates the resulting tool registry.
5. Tests compare the exported manifests with the actual production entry point.

A later capability-factory refactor should replace module side effects behind this
same application boundary. It must not introduce a second public server assembly
path.

## Configuration contract

The application manifest names, but does not reveal values for, the supported
runtime variables:

- `WEAVE_DB_PATH`;
- `WEAVE_BUILD_ROOT`;
- `WEAVEC_BIN`;
- `WEAVEC_SOURCE_ROOT`;
- `WEAVE_BWRAP`.

Paths and secrets are intentionally absent from public composition metadata.
Runtime artifact manifests continue to bind the exact compiler, executable,
sandbox, and content hashes where those identities matter.

## Contributor rules

- Add a new public capability through the declared capability graph.
- Never create another production entry point that bypasses `JacquardApp.compose()`.
- Treat tool-manifest changes as public API changes requiring review and real-MCP
  qualification.
- Keep application identities content-derived and deterministic.
- Do not add environment values or server-local paths to public application
  manifests.
- Preserve `weavec` as the authoritative compiler and language implementation.
