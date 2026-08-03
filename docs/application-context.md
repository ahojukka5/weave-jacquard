# Explicit application context

## Purpose

Jacquard composes the public MCP application around one immutable
`ApplicationContext`. The context identifies the exact FastMCP server and
`RuntimeServices` container selected for that composition.

This boundary prevents capability installation from silently choosing a different
runtime or server than the application being validated. It is also the migration
point for removing the remaining import-time shared-server assumptions tracked by
issue #106.

## Composition model

`JacquardApp.compose()` follows this sequence:

```text
select or create RuntimeServices
→ create ApplicationContext(server, runtime)
→ bind the selected runtime for composition
→ load capabilities in declared dependency order
→ invoke each production lifecycle adapter against that context
→ copy the canonical public tool registry onto context.server
→ install final guidance on context.server
→ clone every public tool with request-time runtime binding
→ capture tool contracts through FastMCPRegistryAdapter
→ validate and hash the public application manifests
```

The resulting `JacquardApp` retains both `server` for compatibility and the complete
`context`. The context is composition state; it is not included in the caller-visible
application manifest, so equivalent public contracts preserve their existing tool and
application identities.

## Production installer contract

The nine production capabilities with lifecycle work are represented by explicit
context-only adapters in `context_capability_installers.py`. Each adapter receives the
selected `ApplicationContext` and the loaded capability module.

The production table covers:

- foundational runtime selection;
- metadata-aware test and merge composition;
- virtual-candidate build and test invalidation;
- tested-merge attestation and revert invalidation;
- database-backup composition;
- artifact accounting and quota reattachment;
- runtime-identity invalidation.

Production composition consults this table before looking at a module-local
`install_capability` function. The historical zero-argument production hooks therefore
are not part of the public application composition path, even when their modules were
already cached before composition.

A custom capability module may expose `install_capability`, but the function must
accept exactly one `ApplicationContext`. Positional and keyword-only context parameters
are supported. Zero-argument, variadic, and multi-argument signatures fail closed
before final guidance or tool registration mutates the application server.

## Tool registration ownership

The full public capability graph is still declared by modules that decorate functions
onto the historical registration server during import. Public composition no longer
assumes that this registration server is the application server.

`application_tool_registration.py` copies the complete canonical tool registry onto
`context.server` before final guidance is installed. The transfer:

- preserves the exact FastMCP-generated tool objects, schemas, annotations, metadata,
  and callable identity;
- replaces stale target tools rather than merging an ambiguous partial registry;
- verifies that source and target public contracts are identical;
- rolls the target registry back if replacement or verification fails;
- is a no-op when the registration server and application server are the same object;
- runs only for the canonical public capability graph, leaving custom graphs and their
  server contents unchanged.

After final guidance is installed, each public FastMCP `Tool` is cloned for the
application. Only its callable and `is_async` execution flag change. The generated
argument model, input and output schemas, descriptions, annotations, icons, metadata,
and public manifest identity remain unchanged.

All SDK-private registry and tool-cloning access remains isolated behind
`FastMCPRegistryAdapter` and `application_tool_registration.py`.

## Request-time runtime ownership

Every cloned public tool contains an asynchronous wrapper around its original
callable. The wrapper selects `context.runtime` before invoking the original function
and retains that selection until any returned awaitable completes.

Runtime selection is task-local through a `ContextVar`. Independent asynchronous tasks
may bind different application runtimes and execute concurrently without observing one
another's configuration or services. Nested bindings restore the previous runtime after
normal return, failure, or cancellation, and synchronous callers use the same scoped
context-manager contract.

A child task inherits the runtime that was selected when the task was created. The
application owner must keep that runtime open until inherited child work has completed.
Resolving services through an inherited binding after its runtime has closed fails with
`RuntimeClosedError` rather than falling back to the process-default container.

Outside an application binding, runtime accessors continue to resolve the process
default. Process lifecycle operations replace or close only that default container;
they do not mutate an application runtime selected in another task.

## Runtime ownership

`ApplicationContext` rejects closed runtime containers. Passing an explicit runtime
to `JacquardApp.compose()` therefore pins capability loading, lifecycle changes, tool
registration, request execution, and the retained application object to one usable
lifecycle owner.

Production adapters also verify that the context runtime is the runtime currently
bound for composition. Cache invalidation, configuration lookup, metadata restoration,
and quota materialization therefore cannot silently target the process-default
container.

## Remaining issue #106 work

Follow-up work must:

- replace import-time registration onto the historical server with direct
  context-server registration, then remove the registry-transfer adapter;
- remove historical module-local production installer calls and remaining import-time
  production mutation;
- construct two complete applications with different databases and artifact roots in
  one process and prove parallel tools, services, manifests, and shutdown do not
  cross-contaminate;
- simplify fixtures once process-global cache clearing is no longer required;
- update the final runtime ownership documentation after the migration boundary is
  removed.

Public MCP tool names, schemas, result contracts, application-manifest formats, and
persisted data formats remain unchanged during this migration.
