# MCP capability registry

Jacquard's public `weave-mcp` process is assembled from one declarative capability
registry in `weave_frontend.mcp_capabilities`.

## Purpose

Feature modules register tools on the shared `FastMCP` server. The public entry
point must not depend on an undocumented chain of imports or repeatedly replace
runtime guidance as each feature is imported.

The registry makes production assembly explicit:

1. validate one ordered capability graph;
2. import each tool-registration module in dependency order;
3. install the final runtime instructions and `weave_help` exactly once;
4. expose the same ordered graph as a deterministic JSON-ready manifest.

## Capability contract

Each capability declares:

- a unique stable name;
- the Python module that registers its public tools;
- the names of capabilities that must already be loaded.

Dependencies must appear before the dependant capability. Missing, forward, or
duplicate dependencies are startup errors rather than implicit import behavior.

The registry preserves caller-visible tool contracts. It does not own service
state, database connections, compiler processes, or feature-specific caches.
Those remain in the existing feature modules and shared workspace services.

## Guidance contract

Tool-registration modules must not install or replace public guidance as an
import side effect. Guidance modules remain pure composers of instructions and
help topics. After every production tool module has loaded, the registry installs
the final composed instructions and `weave_help` once.

This means a new public capability must:

1. add its tool-registration module to `PUBLIC_CAPABILITIES`;
2. declare real dependencies explicitly;
3. extend the final guidance composition when agent instructions are needed;
4. add registry-order and production-startup tests;
5. avoid calling `remove_tool("weave_help")` from its registration module.

## Manifest

`capability_manifest()` returns ordered dictionaries containing `name`, `module`,
and `depends_on`. The manifest is intended for tests, diagnostics, and future
machine-readable runtime discovery. It describes assembly only; it does not claim
that a compiler target, sandbox, or external execution backend is available.
