# Application runtime binding

## Purpose

Capability modules still contain historical import-time installers and runtime-backed
service proxies. An explicit `ApplicationContext` alone is not sufficient if those
proxies continue to resolve the process runtime while a different application is
being composed.

`bind_application_runtime()` provides a narrow composition scope. It temporarily
selects the context runtime while capability modules are loaded, cached installers
are invoked, and final guidance is installed.

## Composition invariant

`install_public_capabilities()` now performs the complete installation sequence
inside one binding:

```text
ApplicationContext(server, runtime)
→ bind runtime for composition
→ import capability module
→ run zero-argument or context-aware installer
→ install final guidance
→ restore the previous process runtime
```

The binding is nested and serialized by the runtime container's reentrant lock.
Calls to `runtime_services()`, `runtime_config()`, runtime-service cache adapters,
and factories decorated with `runtime_service()` therefore resolve the selected
application runtime throughout composition.

The previous process runtime is restored even when module loading or an installer
raises. The binding does not install, replace, or close either runtime. Attempting
to bind a closed container fails before composition begins.

## Isolation provided by this slice

This prevents cached and import-time capability installers from:

- clearing services owned by another application;
- reading another application's database or artifact-root configuration;
- materializing quota, evidence, backup, test, or merge services in the process
  runtime while a different application is being composed.

It also permits two application runtimes to be composed sequentially in one process
without changing which container remains the process default.

## Remaining boundary

The binding currently covers composition only. Tool functions are still decorated
onto the shared FastMCP server during import, and request-time service proxies still
need an application-specific runtime scope.

Issue #106 therefore still requires:

- context-aware signatures for the remaining capability installers;
- explicit tool registration against `context.server`;
- request dispatch that binds `context.runtime`;
- removal of the temporary process-runtime composition adapter;
- two complete concurrently usable applications with distinct database and artifact
  roots;
- final fixture cleanup and lifecycle documentation.

Public MCP names, schemas, application-manifest identities, runtime service-graph
identities, and persisted formats are unchanged.
