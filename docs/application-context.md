# Explicit application context

## Purpose

Jacquard composes the public MCP application around one immutable
`ApplicationContext`. The context identifies the exact FastMCP server and
`RuntimeServices` container selected for that composition.

This boundary prevents capability installation from silently choosing a different
runtime than the application being validated. It is also the migration point for
removing the remaining import-time shared-server assumptions tracked by issue #106.

## Composition model

`JacquardApp.compose()` now follows this sequence:

```text
select or create RuntimeServices
→ create ApplicationContext(server, runtime)
→ bind the selected runtime for composition
→ load capabilities in declared dependency order
→ invoke each production lifecycle adapter against that context
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

## Runtime ownership

`ApplicationContext` rejects closed runtime containers. Passing an explicit runtime
to `JacquardApp.compose()` therefore pins capability loading, lifecycle changes, and
the retained application object to one usable lifecycle owner.

Production adapters also verify that the context runtime is the runtime currently
bound for composition. Cache invalidation, configuration lookup, metadata restoration,
and quota materialization therefore cannot silently target the process-default
container.

This boundary does not yet make MCP tool functions application-local. Existing
decorated capability modules still import the historical shared `mcp` object and
runtime-backed service proxies.

## Remaining issue #106 work

Follow-up work must:

- move tool registration from import-time decorators to context-server installation;
- make service lookup use the application runtime during request execution;
- remove historical module-local installer calls and the custom zero-argument
  compatibility dispatcher;
- construct two complete applications with different databases and artifact roots in
  one process and prove that tools, services, manifests, and shutdown do not
  cross-contaminate;
- simplify fixtures once process-global cache clearing is no longer required.

Public MCP tool names, schemas, result contracts, application-manifest formats, and
persisted data formats remain unchanged during this migration.
