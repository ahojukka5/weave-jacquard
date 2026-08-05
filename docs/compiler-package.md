# Compiler integration package

Jacquard owns compiler integration through the public
`weave_frontend.compiler` package. This boundary contains the complete client
side of the final user-facing `weavec` contract while keeping revision,
artifact-quota, runtime, storage, and MCP composition outside the package.

## Owned responsibilities

The package owns:

- bounded `weavec capabilities --json` execution and registry validation;
- final-compiler binary identity and capability caching;
- frontend validation and WIR retrieval;
- revision-pinned build command construction and bounded process execution;
- ordered compiler input materialization and stable node maps;
- diagnostics and build-manifest protocol validation;
- compiler artifact hashing, cache admission, and publication primitives;
- compiler-specific byte ceilings and bounded text or JSON reads.

The package consumes only lower-level process, source rendering, domain error,
retained-artifact, and grammar primitives. It does not import database
implementations, MCP presentation, runtime composition, artifact quota,
build-target orchestration, or any compiler implementation repository.

## Public API

Application code imports compiler behavior from one surface:

```python
from weave_frontend.compiler import (
    CompilerBridge,
    WeavecCapabilities,
    WeavecValidator,
)
```

`weave_frontend.compiler.__all__` is the supported package surface. Internal
files such as `compiler_bridge.py`, `compiler_capabilities.py`, and
`compiler_manifest.py` are implementation modules inside that package and are
not application composition points.

The quota-aware production bridge remains in
`weave_frontend.quota_aware_compiler_bridge`. It subclasses the public
`CompilerBridge` and adds aggregate artifact admission after compiler work has
completed. The verified workspace remains outside the package and composes the
public capability and validator objects with revision state.

## Compatibility paths

The former flat paths remain temporarily importable:

```python
from weave_frontend.compiler_bridge import CompilerBridge
from weave_frontend.compiler_capabilities import WeavecCapabilities
from weave_frontend.weavec import WeavecValidator
```

These files contain no compiler implementation. Each is a transparent module
alias to its owned package module, so class identity, module-level monkeypatches,
and existing error behavior remain unchanged. New production code must use
`weave_frontend.compiler` directly.

Compatibility paths may be removed only in a deliberate public-API migration.
Adding new logic to them is prohibited.

## Dependency direction

The intended direction is:

```text
MCP / CLI / runtime / revision / quota adapters
                    |
                    v
          weave_frontend.compiler
                    |
                    v
process + source map + grammar + domain errors + retained artifact I/O
                    |
                    v
          final public weavec binary
```

The compiler package must never import `weavec0`, `weavec1`, bootstrap compiler
code, MCP modules, database backends, runtime containers, or application quota
services. Architecture tests enforce the module aliases, absence of flat
implementation bodies, public API, and forbidden upper-layer imports.

## Behavior preservation

This refactor relocates the existing implementation blobs unchanged. Command
construction, capability negotiation, target checks, diagnostics, manifest
validation, artifact identity, caching, limits, and retention behavior remain
owned by the same code. Only package ownership and import direction change.
