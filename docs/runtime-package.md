# Runtime package

The process runtime is owned by `weave_frontend.runtime`. The package captures
immutable startup configuration, owns process and task-local service lifecycles,
selects scoped application runtimes, constructs the production sandbox, and
provides the concrete quota-capable publisher types used by MCP composition.

## Public boundary

Cross-domain Python code imports supported runtime symbols from:

```python
from weave_frontend.runtime import RuntimeConfig, RuntimeServices
```

Production code does not import `runtime.config`, `runtime.container`,
`runtime.binding`, `runtime.sandbox`, or `runtime.publication` directly.

## Internal responsibilities

- `config.py` captures and validates the immutable environment snapshot;
- `container.py` owns deterministic lazy service construction, dependency
  evidence, invalidation, and shutdown;
- `binding.py` selects one runtime for a context and inherited child tasks;
- `sandbox.py` constructs the environment-independent bubblewrap backend;
- `publication.py` defines the concrete compiler, test-run, test-batch, and
  attestation publishers that compose base domains with aggregate quota
  admission.

## Dependency direction

Runtime composition depends on public compiler and artifact quota boundaries and
on the current test and attestation service contracts. Those base domains do not
depend back on runtime. The runtime container constructs the concrete production
compiler bridge directly; no object type mutation, upgrade adapter, forwarding
module, or deprecated import path remains.

Environment variables, service graph formats, cache evidence, sandbox behavior,
MCP contracts, artifact formats, and publication semantics are unchanged.
