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

`JacquardApp.compose()` now follows this sequence:

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
`install_capability` function. The historical zero-argument hooks therefore are not
part of the public application composition path, even when their modules were already
cached before composition.

A generic compatibility dispatcher remains for non-production/custom capability
modules. It supports the prior zero-argument form temporarily, while context-aware
custom installers may accept exactly one `ApplicationContext`. Ambiguous and variadic
signatures fail closed.

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

The current runtime container still exposes a process-global selector. To prevent two
overlapping requests from overwriting it, wrappers use one process-wide asynchronous
gate. The gate:

- serializes public tool execution across application runtimes;
- permits nested calls that retain the same application runtime;
- rejects a nested call that attempts to switch runtimes;
- restores the previous process runtime after success, failure, or cancellation;
- supports both synchronous and asynchronous original tool functions.

This is an isolation compatibility layer, not the final concurrency architecture.
Overlapping requests are safe but execute one at a time while the process-global
runtime selector remains. A later runtime-container change should replace the selector
with task-local state, after which this gate can be removed and tools from independent
applications can execute in parallel.

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

- replace the process-global runtime selector with task-local runtime state and remove
  the serialized request gate;
- replace import-time registration onto the historical server with direct
  context-server registration, then remove the registry-transfer adapter;
- remove historical module-local installer calls and the custom zero-argument
  compatibility dispatcher;
- construct two complete applications with different databases and artifact roots in
  one process and prove parallel tools, services, manifests, and shutdown do not
  cross-contaminate;
- simplify fixtures once process-global cache clearing is no longer required.

Public MCP tool names, schemas, result contracts, application-manifest formats, and
persisted data formats remain unchanged during this migration.
