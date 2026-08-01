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
→ load capabilities in declared dependency order
→ invoke each installer against that context
→ install final guidance on context.server
→ capture tool contracts through FastMCPRegistryAdapter
→ validate and hash the public application manifests
```

The resulting `JacquardApp` retains both `server` for compatibility and the complete
`context`. The context is composition state; it is not included in the caller-visible
application manifest, so equivalent public contracts preserve their existing tool and
application identities.

## Installer contract

Capability installers may currently use one of two signatures:

```python
def install_capability(context: ApplicationContext) -> None:
    ...

def install_capability() -> None:
    ...
```

The one-context form is the target architecture. Installer dispatch rejects
ambiguous signatures, variadic signatures, and installers requiring multiple
arguments.

The zero-argument form is a narrow migration adapter for capability modules whose
tools are still registered on the shared server during import. It does not grant a
second application identity or select another server. New capability installers must
accept `ApplicationContext`.

The foundational `concurrent_nodes` installer is context-aware. When called during
explicit composition it uses `context.runtime` and does not consult the process
runtime singleton. Its no-argument call remains only for direct historical module
imports while import-time registration is being removed.

## Runtime ownership

`ApplicationContext` rejects closed runtime containers. Passing an explicit runtime
to `JacquardApp.compose()` therefore pins capability installation and the retained
application object to one usable lifecycle owner.

This slice does not yet make all MCP tool functions application-local. Existing
decorated capability modules still import the historical shared `mcp` object and
runtime-backed service proxies. The context boundary makes that remaining work
explicit and testable rather than hidden inside composition.

## Remaining issue #106 work

Follow-up work must:

- convert every production capability installer to the one-context signature;
- move tool registration from import-time decorators to context-server installation;
- make service lookup use the application runtime during request execution;
- remove the zero-argument installer compatibility path;
- construct two complete applications with different databases and artifact roots in
  one process and prove that tools, services, manifests, and shutdown do not
  cross-contaminate;
- simplify fixtures once process-global cache clearing is no longer required.

Public MCP tool names, schemas, result contracts, application-manifest formats, and
persisted data formats remain unchanged during this migration.
