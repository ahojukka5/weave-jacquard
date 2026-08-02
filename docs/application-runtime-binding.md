# Application runtime binding

## Purpose

Capability modules still contain historical import-time setup and runtime-backed
service proxies. An explicit `ApplicationContext` alone is not sufficient if those
proxies continue to resolve the process runtime while a different application is
being composed or serving a request.

`bind_application_runtime()` selects one context runtime for composition and tool
execution. Calls to `runtime_services()`, `runtime_config()`, runtime-service cache
adapters, and factories decorated with `runtime_service()` resolve that selected
runtime without changing the process default.

## Task-local selection

The runtime container stores the selected application runtime in a `ContextVar`.
Bindings are nested and restore the previous value when their scope exits, including
when composition or a tool call raises.

Independent asynchronous tasks may bind different runtimes at the same time. They do
not block one another and cannot observe each other's selected services or
configuration. Synchronous callers retain the same nested context-manager behavior.

A child task inherits the selected runtime captured when the task is created. That
inherited binding remains active for the child even after the parent leaves its
binding scope. The application owner must therefore keep the runtime open until all
inherited child work has completed. A child that tries to resolve a runtime after the
inherited container has been closed fails with `RuntimeClosedError`.

## Composition and request invariant

`install_public_capabilities()` performs installation inside one binding, and every
application-bound FastMCP tool enters the same binding before invoking its canonical
function:

```text
ApplicationContext(server, runtime)
→ bind runtime in the current context
→ import or invoke application capability
→ resolve all runtime-backed services from that runtime
→ restore the previous context runtime
```

The binding does not install, replace, or close either runtime. Attempting to bind a
closed container fails before work begins.

## Process lifecycle boundary

`install_runtime_services()`, `reset_runtime_services()`, and
`close_runtime_services()` manage only the process default container. They do not
replace or close a task-local application runtime.

Cache inspection and cache clearing are different: they act on the runtime selected
for the current context, falling back to the process default when no application is
bound. This keeps historical cache-compatible service proxies application-local.

## Isolation provided

The context-only production installer table and request-time tool wrappers prevent
runtime-backed capability setup and execution from:

- clearing services owned by another application;
- reading another application's database or artifact-root configuration;
- materializing quota, evidence, backup, test, or merge services in the process
  runtime while a different application is active;
- serializing unrelated application calls through a process-wide dispatch lock;
- invoking historical zero-argument production hooks during public composition.

Two application runtimes can be composed and used concurrently in one process while
the original process container remains the default outside their task contexts.

## Remaining boundary

Issue #106 still requires removal of the remaining historical module-local installer
calls and compatibility composition paths. The final runtime service graph must own
all production services directly and eliminate import-time production mutation.

Public MCP names, schemas, application-manifest identities, runtime service-graph
identities, and persisted formats are unchanged.
