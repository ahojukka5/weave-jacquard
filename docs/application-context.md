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

All SDK-private registry access remains isolated in `FastMCPRegistryAdapter`. Final
`weave_help` guidance is installed after the transfer, exactly as before.

## Runtime ownership

`ApplicationContext` rejects closed runtime containers. Passing an explicit runtime
to `JacquardApp.compose()` therefore pins capability loading, lifecycle changes, tool
registration, and the retained application object to one usable lifecycle owner.

Production adapters also verify that the context runtime is the runtime currently
bound for composition. Cache invalidation, configuration lookup, metadata restoration,
and quota materialization therefore cannot silently target the process-default
container.

Tool objects are now owned by the selected application server, but their current
functions still resolve runtime-backed service proxies when requests execute. Request
execution therefore needs its own application-runtime binding before two applications
can be used concurrently without cross-contamination.

## Remaining issue #106 work

Follow-up work must:

- bind each tool request to the runtime retained by its `ApplicationContext`;
- replace import-time registration onto the historical server with direct
  context-server registration, then remove the registry-transfer adapter;
- remove historical module-local installer calls and the custom zero-argument
  compatibility dispatcher;
- construct two complete applications with different databases and artifact roots in
  one process and prove that tools, services, manifests, and shutdown do not
  cross-contaminate;
- simplify fixtures once process-global cache clearing is no longer required.

Public MCP tool names, schemas, result contracts, application-manifest formats, and
persisted data formats remain unchanged during this migration.
