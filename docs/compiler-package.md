# Compiler integration package

Jacquard owns final-compiler integration through one package:
`weave_frontend.compiler`.

## Public boundary

Application code imports compiler behavior only from the package surface:

```python
from weave_frontend.compiler import (
    CompilerBridge,
    WeavecCapabilities,
    WeavecValidator,
)
```

The package owns capability negotiation, bounded compiler execution, input
materialization, diagnostics, manifests, artifact verification, and compiler
resource limits. Revision orchestration, artifact quota, runtime composition,
storage, and MCP presentation remain outside this package.

## Internal structure

The implementation modules each own one compiler concern:

- `bridge.py`: revision-pinned build orchestration;
- `capabilities.py`: capability registry validation and lookup;
- `validator.py`: frontend validation and WIR retrieval;
- `inputs.py`: ordered source rendering and materialization;
- `diagnostics.py`: compiler diagnostic validation and node mapping;
- `evidence.py`: strict evidence profiles and their capability requirements;
- `manifest.py`: build-manifest validation;
- `artifacts.py`: artifact identity, verification, and publication primitives;
- `io.py`: bounded compiler-generated file reads;
- `limits.py`: compiler-specific byte ceilings and identity formats.

These modules import lower-level Jacquard primitives directly with parent-package
imports. Pass-through adapter modules are not part of the design.

## Compatibility discipline

The former flat compiler modules were internal implementation paths, not a
supported public compatibility contract. They are removed rather than retained
as aliases or forwarding modules.

Do not add compatibility shims, duplicate import paths, forwarding modules, or
deprecation wrappers without an explicit supported public compatibility
requirement. When an internal boundary changes, migrate every repository caller
and remove the obsolete path in the same change.

## Dependency direction

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

The compiler package must not import MCP modules, database backends, runtime
containers, application quota services, `weavec0`, `weavec1`, or bootstrap
compiler code. Architecture tests enforce the package contents, dependency
direction, and absence of obsolete compiler import paths.
